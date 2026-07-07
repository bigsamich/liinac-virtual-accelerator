// EPICS web-gateway client: PV subscribe/put + JSON-RPC for redis-backed
// features (studies, ask-the-machine, rescue). One WebSocket, one origin.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

class Epics extends ChangeNotifier {
  Epics(this.url) {
    _connect();
  }
  final String url;
  WebSocketChannel? _ch;
  bool connected = false;
  final Map<String, dynamic> values = {};
  final Set<String> _subs = {};
  int _rid = 0;
  final Map<int, Completer<dynamic>> _pending = {};
  final List<String> _sendQueue = [];

  void _connect() {
    try {
      _ch = WebSocketChannel.connect(Uri.parse(url));
      connected = true;
      _ch!.stream.listen(_onMsg, onDone: _retry, onError: (_) => _retry());
      if (_subs.isNotEmpty) {
        _ch!.sink.add(jsonEncode({'op': 'subscribe', 'pvs': _subs.toList()}));
      }
      notifyListeners();
    } catch (_) {
      _retry();
    }
  }

  void _retry() {
    connected = false;
    // fail any in-flight rpcs so callers retry instead of hanging forever
    for (final c in _pending.values) {
      if (!c.isCompleted) c.complete({'error': 'disconnected'});
    }
    _pending.clear();
    notifyListeners();
    Timer(const Duration(seconds: 2), _connect);
  }

  void _onMsg(dynamic data) {
    final m = jsonDecode(data as String) as Map<String, dynamic>;
    if (m['op'] == 'rpc-reply') {
      final c = _pending.remove(m['id']);
      if (c != null && !c.isCompleted) {
        c.complete(m['error'] != null ? {'error': m['error']} : m['result']);
      }
      return;
    }
    final pv = m['pv'] as String?;
    if (pv != null && m.containsKey('value')) {
      values[pv] = m['value'];
      notifyListeners();
    }
  }

  void subscribe(List<String> pvs) {
    _subs.addAll(pvs);
    if (connected) {
      _ch?.sink.add(jsonEncode({'op': 'subscribe', 'pvs': pvs}));
    }
  }

  void _send(String frame) {
    if (connected && _ch != null) {
      _ch!.sink.add(frame);
    } else {
      _sendQueue.add(frame);
    }
  }

  void put(String pv, num value) {
    _send(jsonEncode({'op': 'put', 'pv': pv, 'value': value}));
  }

  Future<dynamic> rpc(String method, [Map<String, dynamic>? args]) {
    final id = ++_rid;
    final c = Completer<dynamic>();
    _pending[id] = c;
    _send(jsonEncode(
        {'op': 'rpc', 'id': id, 'method': method, 'args': args ?? {}}));
    return c.future.timeout(const Duration(seconds: 20), onTimeout: () {
      _pending.remove(id);
      return {'error': 'timeout'};
    });
  }

  double scalar(String pv, [double dflt = 0]) {
    final v = values[pv];
    if (v is num) return v.toDouble();
    return dflt;
  }

  List<double> array(String pv) {
    final v = values[pv];
    if (v is List) return v.map((e) => (e as num).toDouble()).toList();
    return const [];
  }
}

// ---- shared theme
const kBg = Color(0xFF0D1117);
const kCard = Color(0xFF161B22);
const kOk = Color(0xFF2ECC71);
const kWarn = Color(0xFFFFB74D);
const kBad = Color(0xFFE74C3C);
const kAccent = Color(0xFF4FC3F7);

// ---- reusable series painter (line or bars, optional 2nd trace)
class SeriesPainter extends CustomPainter {
  SeriesPainter(this.data, this.color,
      {this.data2,
      this.color2,
      this.bars = false,
      this.symmetric = false,
      this.floor});
  final List<double> data;
  final List<double>? data2;
  final Color color;
  final Color? color2;
  final bool bars, symmetric;
  final double? floor;

  @override
  void paint(Canvas canvas, Size size) {
    if (data.isEmpty) return;
    double lo = data.reduce((a, b) => a < b ? a : b);
    double hi = data.reduce((a, b) => a > b ? a : b);
    if (data2 != null && data2!.isNotEmpty) {
      lo = [lo, ...data2!].reduce((a, b) => a < b ? a : b);
      hi = [hi, ...data2!].reduce((a, b) => a > b ? a : b);
    }
    if (symmetric) {
      final m = hi.abs() > lo.abs() ? hi.abs() : lo.abs();
      hi = m;
      lo = -m;
    }
    if (floor != null && lo > floor!) lo = floor!;
    if ((hi - lo).abs() < 1e-12) hi = lo + 1;
    double ty(double v) => size.height * (1 - (v - lo) / (hi - lo));
    final grid = Paint()
      ..color = Colors.white10
      ..strokeWidth = 1;
    for (var g = 0; g <= 4; g++) {
      final y = size.height * g / 4;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    void draw(List<double> d, Color c) {
      if (bars) {
        final bw = size.width / d.length;
        final fill = Paint()..color = c.withOpacity(0.85);
        final base = ty(lo < 0 && hi > 0 ? 0.0 : lo);
        for (var i = 0; i < d.length; i++) {
          canvas.drawRect(
              Rect.fromLTRB(i * bw + 0.5, ty(d[i]), (i + 1) * bw - 0.5, base),
              fill);
        }
      } else {
        final p = Paint()
          ..color = c
          ..strokeWidth = 1.6
          ..style = PaintingStyle.stroke;
        final path = Path();
        for (var i = 0; i < d.length; i++) {
          final x = size.width * i / (d.length > 1 ? d.length - 1 : 1);
          i == 0 ? path.moveTo(x, ty(d[i])) : path.lineTo(x, ty(d[i]));
        }
        canvas.drawPath(path, p);
      }
    }

    draw(data, color);
    if (data2 != null && data2!.isNotEmpty) draw(data2!, color2 ?? kWarn);
    for (final e in [
      [hi, 2.0],
      [lo, size.height - 14]
    ]) {
      final tp = TextPainter(
          text: TextSpan(
              text: (e[0]).toStringAsFixed(2),
              style: const TextStyle(color: Colors.white38, fontSize: 11)),
          textDirection: TextDirection.ltr)
        ..layout();
      tp.paint(canvas, Offset(4, e[1]));
    }
  }

  @override
  bool shouldRepaint(covariant SeriesPainter old) => true;
}

Widget chartCard(String title, Widget child) => Card(
    child: Padding(
        padding: const EdgeInsets.all(10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(title, style: const TextStyle(color: Colors.white70)),
          const SizedBox(height: 4),
          Expanded(child: child),
        ])));
