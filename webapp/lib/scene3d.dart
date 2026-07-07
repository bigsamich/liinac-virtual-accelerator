// Software 3D machine view — projected scene in a CustomPainter with
// orbit/rotate/zoom, section filtering, spot-size envelope, orbit markers,
// loss spikes. No WebGL dependency.
import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'epics.dart';

const double kExag = 0.3; // display metres per mm (transverse exaggeration)

class Cam {
  double yaw = -1.55, pitch = 0.55, dist = 120, tx = 90, ty = 0, tz = 0;
}

class Prim {
  Prim(this.pts, this.color, {this.width = 1.5, this.close = false});
  final List<List<double>> pts; // 3D points
  final Color color;
  final double width;
  final bool close;
  double depth = 0;
}

class Scene3DPainter extends CustomPainter {
  Scene3DPainter(this.prims, this.cam);
  final List<Prim> prims;
  final Cam cam;

  @override
  void paint(Canvas canvas, Size size) {
    final cy = math.cos(cam.pitch), sy = math.sin(cam.pitch);
    final cz = math.cos(cam.yaw), sz = math.sin(cam.yaw);
    final camPos = [
      cam.tx + cam.dist * cy * cz,
      cam.ty + cam.dist * cy * sz,
      cam.tz + cam.dist * sy
    ];
    final f = _norm([cam.tx - camPos[0], cam.ty - camPos[1], cam.tz - camPos[2]]);
    var r = _norm(_cross(f, [0, 0, 1.0]));
    if (r[0].isNaN) r = [1, 0, 0];
    final u = _cross(r, f);
    final focal = size.width * 0.85;

    List<double>? proj(List<double> p) {
      final rel = [p[0] - camPos[0], p[1] - camPos[1], p[2] - camPos[2]];
      final zf = _dot(rel, f);
      if (zf < 0.5) return null;
      final xr = _dot(rel, r), yu = _dot(rel, u);
      return [size.width / 2 + xr / zf * focal,
              size.height / 2 - yu / zf * focal, zf];
    }

    for (final pr in prims) {
      var zsum = 0.0, n = 0;
      for (final p in pr.pts) {
        final rel = [p[0] - camPos[0], p[1] - camPos[1], p[2] - camPos[2]];
        zsum += _dot(rel, f);
        n++;
      }
      pr.depth = n > 0 ? zsum / n : 1e9;
    }
    prims.sort((a, b) => b.depth.compareTo(a.depth));

    for (final pr in prims) {
      final paint = Paint()
        ..color = pr.color
        ..strokeWidth = pr.width
        ..style = PaintingStyle.stroke
        ..strokeCap = StrokeCap.round;
      final path = Path();
      var started = false;
      for (final p in pr.pts) {
        final s = proj(p);
        if (s == null) {
          started = false;
          continue;
        }
        if (!started) {
          path.moveTo(s[0], s[1]);
          started = true;
        } else {
          path.lineTo(s[0], s[1]);
        }
      }
      if (pr.close && started) path.close();
      canvas.drawPath(path, paint);
    }
  }

  static List<double> _cross(List<double> a, List<double> b) =>
      [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
       a[0] * b[1] - a[1] * b[0]];
  static double _dot(List<double> a, List<double> b) =>
      a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  static List<double> _norm(List<double> a) {
    final m = math.sqrt(_dot(a, a));
    return m < 1e-9 ? a : [a[0] / m, a[1] / m, a[2] / m];
  }

  @override
  bool shouldRepaint(covariant Scene3DPainter o) => true;
}

// ------------------------------------------------------------ machine page

class Machine3DPage extends StatefulWidget {
  const Machine3DPage({super.key, required this.e});
  final Epics e;
  @override
  State<Machine3DPage> createState() => _Machine3DPageState();
}

class _Machine3DPageState extends State<Machine3DPage> {
  final cam = Cam();
  Map geo = {};
  List rings = [];
  List<String> sections = [];
  String? section;
  bool showElems = true, showEnv = true, showOrbit = true, showLoss = true;
  double _startDist = 120;
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _loadGeo();
    _t = Timer.periodic(const Duration(seconds: 1), (_) => _loadEnv());
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  void _loadGeo() async {
    final r = await widget.e
        .rpc('geometry', section == null ? {} : {'section': section});
    if (r is Map && mounted) {
      setState(() {
        geo = r;
        sections = ((r['sec_names'] as List?) ?? []).cast<String>();
      });
      _frame();
      _loadEnv();
    }
  }

  void _loadEnv() async {
    final r = await widget.e
        .rpc('envelope', section == null ? {} : {'section': section});
    if (r is Map && r['rings'] != null && mounted) {
      setState(() => rings = r['rings']);
    }
  }

  void _frame() {
    final els = (geo['elements'] as List?) ?? [];
    if (els.isEmpty) return;
    double sx = 0, sy = 0, mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9;
    for (final e in els) {
      sx += e['x'];
      sy += e['y'];
      mnx = math.min(mnx, e['x']);
      mxx = math.max(mxx, e['x']);
      mny = math.min(mny, e['y']);
      mxy = math.max(mxy, e['y']);
    }
    cam.tx = sx / els.length;
    cam.ty = sy / els.length;
    cam.tz = 0;
    cam.dist = math.max(12, (mxx - mnx + mxy - mny) * 0.6);
    _startDist = cam.dist;
  }

  List<Prim> _build() {
    final prims = <Prim>[];
    final poly = (geo['poly'] as List?) ?? [];
    if (showElems) {
      prims.add(Prim([for (final p in poly) [p[0], p[1], 0.0]],
          Colors.white24, width: 1.0));
      for (final e in (geo['elements'] as List?) ?? []) {
        final th = e['th'], l = e['len'] / 2;
        final dx = math.cos(th) * l, dy = math.sin(th) * l;
        prims.add(Prim([
          [e['x'] - dx, e['y'] - dy, 0.0],
          [e['x'] + dx, e['y'] + dy, 0.0]
        ], Color.fromARGB(255, e['rgb'][0], e['rgb'][1], e['rgb'][2]),
            width: 4));
      }
    }
    if (showEnv) {
      for (final rg in rings) {
        final pts = <List<double>>[];
        for (var k = 0; k <= 14; k++) {
          final ph = k / 14 * 2 * math.pi;
          final ht = (rg['cx'] + 2 * rg['sx'] * math.cos(ph)) * kExag;
          final vt = (rg['cy'] + 2 * rg['sy'] * math.sin(ph)) * kExag;
          pts.add([rg['x'] + rg['nx'] * ht, rg['y'] + rg['ny'] * ht, vt]);
        }
        prims.add(Prim(pts, const Color(0x6633E0A0), width: 1.2, close: true));
      }
    }
    if (showOrbit) {
      final xs = widget.e.array('PIP2:BPM:X');
      final ys = widget.e.array('PIP2:BPM:Y');
      for (final m in (geo['bpm'] as List?) ?? []) {
        final g = m['g'] as int;
        if (g >= xs.length) continue;
        final ht = xs[g] * kExag, vt = ys[g] * kExag;
        final cx = m['x'] + m['nx'] * ht, cy = m['y'] + m['ny'] * ht;
        prims.add(Prim([
          [cx - 0.3, cy, vt],
          [cx + 0.3, cy, vt]
        ], const Color(0xFF33FF88), width: 5));
      }
    }
    if (showLoss) {
      final w = widget.e.array('PIP2:BLM:WPM');
      for (final m in (geo['blm'] as List?) ?? []) {
        final g = m['g'] as int;
        final loss = g < w.length ? w[g] : 0.0;
        final h = 2.0 * (math.log(1 + math.max(loss, 0)) / math.ln10);
        if (h < 0.05) continue;
        prims.add(Prim([
          [m['x'], m['y'], 0.0],
          [m['x'], m['y'], h]
        ], const Color(0xFFFF4030), width: 2));
      }
    }
    return prims;
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(8),
      child: Column(children: [
        Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          DropdownButton<String?>(
            value: section,
            dropdownColor: kCard,
            hint: const Text('full machine'),
            items: [
              const DropdownMenuItem(value: null, child: Text('full machine')),
              for (final s in sections)
                DropdownMenuItem(value: s, child: Text(s)),
            ],
            onChanged: (v) => setState(() {
              section = v;
              _loadGeo();
            }),
          ),
          _tog('elements', showElems, (v) => setState(() => showElems = v)),
          _tog('spot size', showEnv, (v) => setState(() => showEnv = v)),
          _tog('orbit', showOrbit, (v) => setState(() => showOrbit = v)),
          _tog('losses', showLoss, (v) => setState(() => showLoss = v)),
          IconButton(
              tooltip: 'top',
              onPressed: () => setState(() {
                    cam.pitch = 1.55;
                    cam.yaw = -1.55;
                  }),
              icon: const Icon(Icons.vertical_align_center)),
          IconButton(
              tooltip: 'side',
              onPressed: () => setState(() {
                    cam.pitch = 0.02;
                    cam.yaw = -1.55;
                  }),
              icon: const Icon(Icons.view_agenda)),
          IconButton(
              tooltip: 'iso',
              onPressed: () => setState(() {
                    cam.pitch = 0.55;
                    cam.yaw = -1.55;
                    _frame();
                  }),
              icon: const Icon(Icons.threed_rotation)),
        ]),
        Expanded(
          child: Card(
            child: ClipRect(
              child: GestureDetector(
                onScaleStart: (d) => _startDist = cam.dist,
                onScaleUpdate: (d) => setState(() {
                  if (d.pointerCount >= 2) {
                    cam.dist = (_startDist / d.scale).clamp(3.0, 400.0);
                  }
                  cam.yaw -= d.focalPointDelta.dx * 0.008;
                  cam.pitch = (cam.pitch + d.focalPointDelta.dy * 0.008)
                      .clamp(-1.55, 1.55);
                }),
                child: CustomPaint(
                    size: Size.infinite,
                    painter: Scene3DPainter(_build(), cam)),
              ),
            ),
          ),
        ),
        const Text('drag = rotate · pinch = zoom · presets above',
            style: TextStyle(color: Colors.white38, fontSize: 11)),
      ]),
    );
  }

  Widget _tog(String label, bool v, void Function(bool) f) => FilterChip(
      label: Text(label, style: const TextStyle(fontSize: 12)),
      selected: v,
      onSelected: f);
}

// -------------------------------------------------------- profile spot size

class Profile3DPage extends StatefulWidget {
  const Profile3DPage({super.key, required this.e});
  final Epics e;
  @override
  State<Profile3DPage> createState() => _Profile3DPageState();
}

class _Profile3DPageState extends State<Profile3DPage> {
  Map cloud = {};
  List rings = [];
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 1), (_) => _load());
    _load();
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  void _load() async {
    final c = await widget.e.rpc('cloud');
    final en = await widget.e.rpc('envelope');
    if (mounted) {
      setState(() {
        if (c is Map) cloud = c;
        if (en is Map && en['rings'] != null) rings = en['rings'];
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    // spot size at mid-machine ring for the ellipse
    Map? rg = rings.isNotEmpty ? rings[rings.length ~/ 2] : null;
    final st = cloud['station'] ?? '(select on Profiles page)';
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(children: [
        Card(
            child: ListTile(
                dense: true,
                title: Text('Beam spot — GPU cloud @ $st'),
                subtitle: rg == null
                    ? null
                    : Text(
                        'σx=${rg['sx'].toStringAsFixed(2)} mm  '
                        'σy=${rg['sy'].toStringAsFixed(2)} mm (mid-linac)'))),
        Expanded(
          child: Card(
            child: CustomPaint(
                size: Size.infinite,
                painter: SpotPainter(
                    (cloud['x'] as List?)?.cast<num>() ?? [],
                    (cloud['y'] as List?)?.cast<num>() ?? [],
                    rg == null ? 0 : rg['sx'].toDouble(),
                    rg == null ? 0 : rg['sy'].toDouble())),
          ),
        ),
        SizedBox(
            height: 130,
            child: chartCard(
                'σx / σy along the machine [mm]',
                CustomPaint(
                    size: Size.infinite,
                    painter: SeriesPainter(
                        [for (final r in rings) (r['sx'] as num).toDouble()],
                        kAccent,
                        data2: [
                          for (final r in rings) (r['sy'] as num).toDouble()
                        ],
                        color2: kWarn,
                        floor: 0)))),
      ]),
    );
  }
}

class SpotPainter extends CustomPainter {
  SpotPainter(this.x, this.y, this.sx, this.sy);
  final List<num> x, y;
  final double sx, sy;
  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2, cy = size.height / 2;
    // scale: fit ±5 mm
    final sc = math.min(size.width, size.height) / 12;
    final grid = Paint()..color = Colors.white12;
    canvas.drawLine(Offset(0, cy), Offset(size.width, cy), grid);
    canvas.drawLine(Offset(cx, 0), Offset(cx, size.height), grid);
    final dot = Paint()..color = const Color(0x5533E0FF);
    for (var i = 0; i < x.length; i++) {
      canvas.drawCircle(
          Offset(cx + x[i] * sc, cy - y[i] * sc), 1.2, dot);
    }
    if (sx > 0) {
      final ell = Paint()
        ..color = kWarn
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2;
      for (final k in [1.0, 2.0]) {
        final path = Path();
        for (var a = 0; a <= 40; a++) {
          final ph = a / 40 * 2 * math.pi;
          final px = cx + k * sx * math.cos(ph) * sc;
          final py = cy - k * sy * math.sin(ph) * sc;
          a == 0 ? path.moveTo(px, py) : path.lineTo(px, py);
        }
        canvas.drawPath(path, ell..color = kWarn.withOpacity(k == 1 ? 0.9 : 0.4));
      }
    }
    final tp = TextPainter(
        text: const TextSpan(
            text: '±5 mm  · 1σ/2σ ellipse',
            style: TextStyle(color: Colors.white38, fontSize: 11)),
        textDirection: TextDirection.ltr)
      ..layout();
    tp.paint(canvas, const Offset(6, 6));
  }

  @override
  bool shouldRepaint(covariant SpotPainter o) => true;
}
