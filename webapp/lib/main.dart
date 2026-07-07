// PIP-II VA console — Flutter web client for the EPICS web gateway.
// Talks the pvws-style WebSocket JSON protocol served at /ws on the same
// origin (one endpoint: app + data). PV names follow ED0011740.
import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

void main() => runApp(const Pip2App());

// ---------------------------------------------------------------- WS layer

class Epics extends ChangeNotifier {
  Epics(this.url) {
    _connect();
  }
  final String url;
  WebSocketChannel? _ch;
  bool connected = false;
  final Map<String, dynamic> values = {};
  final Set<String> _subs = {};

  void _connect() {
    try {
      _ch = WebSocketChannel.connect(Uri.parse(url));
      connected = true;
      _ch!.stream.listen(_onMsg, onDone: _retry, onError: (_) => _retry());
      if (_subs.isNotEmpty) {
        _ch!.sink.add(jsonEncode(
            {'op': 'subscribe', 'pvs': _subs.toList()}));
      }
      notifyListeners();
    } catch (_) {
      _retry();
    }
  }

  void _retry() {
    connected = false;
    notifyListeners();
    Timer(const Duration(seconds: 3), _connect);
  }

  void _onMsg(dynamic data) {
    final m = jsonDecode(data as String) as Map<String, dynamic>;
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

  void put(String pv, num value) {
    _ch?.sink.add(jsonEncode({'op': 'put', 'pv': pv, 'value': value}));
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

// ------------------------------------------------------------------- app

const kBg = Color(0xFF0D1117);
const kCard = Color(0xFF161B22);
const kOk = Color(0xFF2ECC71);
const kWarn = Color(0xFFFFB74D);
const kBad = Color(0xFFE74C3C);
const kAccent = Color(0xFF4FC3F7);

class Pip2App extends StatefulWidget {
  const Pip2App({super.key});
  @override
  State<Pip2App> createState() => _Pip2AppState();
}

class _Pip2AppState extends State<Pip2App> {
  late final Epics epics;
  int page = 0;

  @override
  void initState() {
    super.initState();
    final loc = Uri.base;
    final scheme = loc.scheme == 'https' ? 'wss' : 'ws';
    // authority = host:port — Uri.host alone drops the port (ws would
    // silently aim at :80 and the app shows no values)
    epics = Epics('$scheme://${loc.authority}/ws');
    epics.subscribe(const [
      'PIP2:BEAM:W', 'PIP2:BEAM:T', 'PIP2:BEAM:IOUT', 'PIP2:BEAM:PULSE',
      'PIP2:MPS:PERMIT', 'PIP2:BPM:X', 'PIP2:BPM:Y', 'PIP2:BLM:WPM',
      'PIP2:BCM:I', 'PIP2:VAC:TORR',
    ]);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PIP-II VA',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true).copyWith(
          scaffoldBackgroundColor: kBg, cardColor: kCard),
      home: AnimatedBuilder(
        animation: epics,
        builder: (context, _) => Scaffold(
          body: Row(children: [
            NavigationRail(
              selectedIndex: page,
              onDestinationSelected: (i) => setState(() => page = i),
              backgroundColor: kCard,
              labelType: NavigationRailLabelType.all,
              destinations: const [
                NavigationRailDestination(
                    icon: Icon(Icons.dashboard), label: Text('Status')),
                NavigationRailDestination(
                    icon: Icon(Icons.show_chart), label: Text('Orbit')),
                NavigationRailDestination(
                    icon: Icon(Icons.warning_amber), label: Text('Losses')),
                NavigationRailDestination(
                    icon: Icon(Icons.settings_input_antenna),
                    label: Text('RF')),
              ],
            ),
            Expanded(
                child: [
              StatusPage(epics: epics),
              ArrayPage(
                  epics: epics,
                  pv: 'PIP2:BPM:X',
                  pv2: 'PIP2:BPM:Y',
                  title: 'Orbit x/y [mm]',
                  color: kAccent,
                  color2: kWarn,
                  symmetric: true),
              ArrayPage(
                  epics: epics,
                  pv: 'PIP2:BLM:WPM',
                  title: 'Beam loss [W/m]',
                  color: kBad,
                  bars: true),
              RfPage(epics: epics),
            ][page]),
          ]),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------- status

class StatusPage extends StatelessWidget {
  const StatusPage({super.key, required this.epics});
  final Epics epics;

  @override
  Widget build(BuildContext context) {
    final permit = epics.scalar('PIP2:MPS:PERMIT') > 0.5;
    return Padding(
      padding: const EdgeInsets.all(16),
      child:
          Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Card(
          color: permit ? const Color(0xFF11331E) : const Color(0xFF3A1414),
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: Row(children: [
              Icon(Icons.circle, color: permit ? kOk : kBad, size: 18),
              const SizedBox(width: 10),
              Text(
                  permit
                      ? 'BEAM PERMIT: ENABLED'
                      : 'BEAM PERMIT: INHIBITED',
                  style: const TextStyle(
                      fontSize: 20, fontWeight: FontWeight.bold)),
              const Spacer(),
              FilledButton.tonal(
                onPressed: () => epics.put('PIP2:MPS:RESET', 1),
                child: const Text('RESET PERMIT'),
              ),
              const SizedBox(width: 8),
              Text(epics.connected ? 'link ●' : 'link ○',
                  style: TextStyle(color: epics.connected ? kOk : kBad)),
            ]),
          ),
        ),
        const SizedBox(height: 12),
        Row(children: [
          _big('Energy', epics.scalar('PIP2:BEAM:W').toStringAsFixed(1),
              'MeV', kAccent),
          _big(
              'Transmission',
              (100 * epics.scalar('PIP2:BEAM:T')).toStringAsFixed(2),
              '%',
              epics.scalar('PIP2:BEAM:T') > 0.95 ? kOk : kBad),
          _big('Delivered',
              epics.scalar('PIP2:BEAM:IOUT').toStringAsFixed(3), 'mA',
              kAccent),
          _big('Pulse', epics.scalar('PIP2:BEAM:PULSE').toStringAsFixed(0),
              '', Colors.white70),
        ]),
        const SizedBox(height: 12),
        Expanded(
            child: Row(children: [
          Expanded(
              child: _mini('BCM currents [mA]', epics.array('PIP2:BCM:I'),
                  kOk)),
          const SizedBox(width: 12),
          Expanded(
              child: _mini(
                  'Vacuum log10(P) [torr]',
                  epics
                      .array('PIP2:VAC:TORR')
                      .map((p) => p > 0 ? math.log(p) / math.ln10 : -10.0)
                      .toList(),
                  const Color(0xFFBA68C8))),
        ])),
      ]),
    );
  }

  Widget _big(String label, String v, String unit, Color c) => Expanded(
      child: Card(
          child: Padding(
              padding: const EdgeInsets.all(14),
              child: Column(children: [
                Text(label,
                    style: const TextStyle(
                        color: Colors.white54, fontSize: 13)),
                Text(v,
                    style: TextStyle(
                        fontSize: 34,
                        fontWeight: FontWeight.bold,
                        color: c)),
                Text(unit, style: const TextStyle(color: Colors.white38)),
              ]))));

  Widget _mini(String title, List<double> data, Color color) => Card(
      child: Padding(
          padding: const EdgeInsets.all(10),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(color: Colors.white70)),
                Expanded(
                    child: CustomPaint(
                        size: Size.infinite,
                        painter: SeriesPainter(data, color, bars: true))),
              ])));
}

// ------------------------------------------------------------ array pages

class ArrayPage extends StatelessWidget {
  const ArrayPage(
      {super.key,
      required this.epics,
      required this.pv,
      this.pv2,
      required this.title,
      required this.color,
      this.color2,
      this.bars = false,
      this.symmetric = false});
  final Epics epics;
  final String pv, title;
  final String? pv2;
  final Color color;
  final Color? color2;
  final bool bars, symmetric;

  @override
  Widget build(BuildContext context) {
    return Padding(
        padding: const EdgeInsets.all(16),
        child: Card(
            child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title, style: const TextStyle(fontSize: 16)),
                      Expanded(
                          child: CustomPaint(
                              size: Size.infinite,
                              painter: SeriesPainter(
                                  epics.array(pv), color,
                                  data2:
                                      pv2 == null ? null : epics.array(pv2!),
                                  color2: color2,
                                  bars: bars,
                                  symmetric: symmetric))),
                    ]))));
  }
}

class SeriesPainter extends CustomPainter {
  SeriesPainter(this.data, this.color,
      {this.data2, this.color2, this.bars = false, this.symmetric = false});
  final List<double> data;
  final List<double>? data2;
  final Color color;
  final Color? color2;
  final bool bars, symmetric;

  @override
  void paint(Canvas canvas, Size size) {
    if (data.isEmpty) return;
    var lo = data.reduce(math.min), hi = data.reduce(math.max);
    if (data2 != null && data2!.isNotEmpty) {
      lo = math.min(lo, data2!.reduce(math.min));
      hi = math.max(hi, data2!.reduce(math.max));
    }
    if (symmetric) {
      final m = math.max(hi.abs(), lo.abs());
      hi = m;
      lo = -m;
    }
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
        final base = ty(math.max(lo, math.min(0.0, hi)));
        for (var i = 0; i < d.length; i++) {
          canvas.drawRect(
              Rect.fromLTRB(
                  i * bw + 1, ty(d[i]), (i + 1) * bw - 1, base),
              fill);
        }
      } else {
        final p = Paint()
          ..color = c
          ..strokeWidth = 1.6
          ..style = PaintingStyle.stroke;
        final path = Path();
        for (var i = 0; i < d.length; i++) {
          final x = size.width * i / math.max(d.length - 1, 1);
          i == 0 ? path.moveTo(x, ty(d[i])) : path.lineTo(x, ty(d[i]));
        }
        canvas.drawPath(path, p);
      }
    }

    draw(data, color);
    if (data2 != null && data2!.isNotEmpty) draw(data2!, color2 ?? kWarn);
    final tp = TextPainter(
        text: TextSpan(
            text: hi.toStringAsFixed(2),
            style: const TextStyle(color: Colors.white38, fontSize: 11)),
        textDirection: TextDirection.ltr)
      ..layout();
    tp.paint(canvas, const Offset(4, 2));
    final tp2 = TextPainter(
        text: TextSpan(
            text: lo.toStringAsFixed(2),
            style: const TextStyle(color: Colors.white38, fontSize: 11)),
        textDirection: TextDirection.ltr)
      ..layout();
    tp2.paint(canvas, Offset(4, size.height - 14));
  }

  @override
  bool shouldRepaint(covariant SeriesPainter old) => true;
}

// ---------------------------------------------------------------- RF page

class RfPage extends StatefulWidget {
  const RfPage({super.key, required this.epics});
  final Epics epics;
  @override
  State<RfPage> createState() => _RfPageState();
}

class _RfPageState extends State<RfPage> {
  // representative cavities, official ED0011740 PV bases
  static const cavs = [
    ['HWR CAV4', 'LSCL:HWR-1_LLRF_CAV1104'],
    ['SSR1 CAV11', 'LSCL:SSR1-2_LLRF_CAV2203'],
    ['SSR2 CAV17', 'LSCL:SSR2-4_LLRF_CAV3402'],
    ['LB650 CAV22', 'LSCL:LB-6_LLRF_CAV4602'],
    ['HB650 CAV12', 'LSCL:HB-2_LLRF_CAV5206'],
    ['HB650 CAV36', 'LSCL:HB-6_LLRF_CAV5606'],
  ];

  @override
  void initState() {
    super.initState();
    widget.epics.subscribe([
      for (final c in cavs) ...[
        '${c[1]}:AMPL',
        '${c[1]}:PHS',
        '${c[1]}:DET'
      ]
    ]);
  }

  @override
  Widget build(BuildContext context) {
    final e = widget.epics;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Card(
        child: ListView(
          children: [
            const ListTile(
                title: Text('RF cavities (official ED0011740 PVs)'),
                subtitle: Text('tap a row to set phase')),
            for (final c in cavs)
              ListTile(
                title: Text(c[0]),
                subtitle: Text(c[1],
                    style: const TextStyle(
                        color: Colors.white38, fontSize: 11)),
                trailing: Text(
                    '${e.scalar('${c[1]}:AMPL').toStringAsFixed(2)} MV   '
                    '${e.scalar('${c[1]}:PHS').toStringAsFixed(1)}°   '
                    '${e.scalar('${c[1]}:DET').toStringAsFixed(1)} Hz',
                    style: const TextStyle(
                        fontFamily: 'monospace', fontSize: 14)),
                onTap: () => _setPhase(context, c[0], c[1]),
              ),
          ],
        ),
      ),
    );
  }

  Future<void> _setPhase(
      BuildContext context, String label, String base) async {
    final ctl = TextEditingController(
        text: widget.epics.scalar('$base:PHS').toStringAsFixed(1));
    final v = await showDialog<double>(
        context: context,
        builder: (c) => AlertDialog(
              title: Text('$label — set phase [deg]'),
              content: TextField(
                  controller: ctl,
                  keyboardType: TextInputType.number,
                  autofocus: true),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(c),
                    child: const Text('Cancel')),
                FilledButton(
                    onPressed: () =>
                        Navigator.pop(c, double.tryParse(ctl.text)),
                    child: const Text('Apply')),
              ],
            ));
    if (v != null) widget.epics.put('$base:sPHS', v);
  }
}
