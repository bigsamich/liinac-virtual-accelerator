// Additional console pages: device control, MPS, snapshots, physics,
// strip tool, profiles/scans, bunch monitor, machine synoptic, training.
import 'dart:async';
import 'dart:collection';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'epics.dart';

// --------------------------------------------------- device table (RB+SP)

class DeviceTablePage extends StatefulWidget {
  const DeviceTablePage(
      {super.key, required this.e, required this.cls, required this.title});
  final Epics e;
  final String cls, title;
  @override
  State<DeviceTablePage> createState() => _DeviceTablePageState();
}

class _DeviceTablePageState extends State<DeviceTablePage> {
  List devices = [];
  String filter = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() async {
    final r = await widget.e.rpc('device_list', {'cls': widget.cls});
    if (r is Map && r['devices'] != null && mounted) {
      devices = r['devices'];
      final rbs = <String>[];
      for (final d in devices) {
        if (widget.cls == 'magnet') {
          rbs.add(d['rb']);
        } else {
          rbs..add(d['amp_rb'])..add(d['ph_rb'])..add(d['det_rb']);
        }
      }
      widget.e.subscribe(rbs);
      setState(() {});
    }
  }

  @override
  Widget build(BuildContext context) {
    final shown = devices
        .where((d) => filter.isEmpty ||
            (d['name'] as String).toLowerCase().contains(filter))
        .toList();
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(children: [
        TextField(
          onChanged: (t) => setState(() => filter = t.toLowerCase()),
          decoration: InputDecoration(
              isDense: true,
              prefixIcon: const Icon(Icons.search),
              border: const OutlineInputBorder(),
              hintText: '${widget.title} — filter ${devices.length} devices'),
        ),
        const SizedBox(height: 8),
        Expanded(
          child: Card(
            child: ListView.builder(
              itemCount: shown.length,
              itemBuilder: (c, i) {
                final d = shown[i];
                if (widget.cls == 'magnet') {
                  final v = widget.e.scalar(d['rb']);
                  return ListTile(
                    dense: true,
                    title: Text(d['name']),
                    subtitle: Text(d['official'],
                        style: const TextStyle(
                            color: Colors.white38, fontSize: 10)),
                    trailing: Text('${v.toStringAsFixed(2)} A',
                        style: const TextStyle(fontFamily: 'monospace')),
                    onTap: () => setNum(context, widget.e,
                        '${d['name']} current [A]', d['sp'], v),
                  );
                }
                return ListTile(
                  dense: true,
                  title: Text(d['name']),
                  trailing: Text(
                      '${widget.e.scalar(d['amp_rb']).toStringAsFixed(2)} MV  '
                      '${widget.e.scalar(d['ph_rb']).toStringAsFixed(1)}°  '
                      '${widget.e.scalar(d['det_rb']).toStringAsFixed(0)} Hz',
                      style: const TextStyle(fontFamily: 'monospace')),
                  onTap: () => setNum(context, widget.e,
                      '${d['name']} phase [deg]', d['ph_sp'],
                      widget.e.scalar(d['ph_rb'])),
                );
              },
            ),
          ),
        ),
      ]),
    );
  }
}

// ----------------------------------------------------------- source/LEBT

class SourcePage extends StatefulWidget {
  const SourcePage({super.key, required this.e});
  final Epics e;
  @override
  State<SourcePage> createState() => _SourcePageState();
}

class _SourcePageState extends State<SourcePage> {
  Map src = {}, chop = {};
  void _load() async {
    final s = await widget.e.rpc('settings', {'cls': 'source'});
    final c = await widget.e.rpc('settings', {'cls': 'chopper'});
    if (mounted) setState(() {
          src = s is Map ? s : {};
          chop = c is Map ? c : {};
        });
    Future.delayed(const Duration(seconds: 3), _load);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final leg = (src['leg'] ?? 'A').toString();
    return Padding(
      padding: const EdgeInsets.all(12),
      child: ListView(children: [
        Card(
            child: Padding(
          padding: const EdgeInsets.all(14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('Ion source', style: TextStyle(fontSize: 16)),
                const SizedBox(height: 8),
                Row(children: [
                  const Text('Current [mA]: '),
                  Text(src['current_ma'] ?? '—',
                      style: const TextStyle(
                          fontFamily: 'monospace', fontSize: 16)),
                  const Spacer(),
                  FilledButton.tonal(
                    onPressed: () => setNumRpc(context, widget.e,
                        'Source current [mA]', 'source', 'current_ma',
                        double.tryParse('${src['current_ma']}') ?? 5.0),
                    child: const Text('Set'),
                  ),
                ]),
                const Divider(),
                Row(children: [
                  const Text('Active leg: '),
                  SegmentedButton<String>(
                    segments: const [
                      ButtonSegment(value: 'A', label: Text('A (East 0110)')),
                      ButtonSegment(value: 'B', label: Text('B (West 0120)')),
                    ],
                    selected: {leg},
                    onSelectionChanged: (s) => widget.e
                        .rpc('set', {
                          'cls': 'source',
                          'field': 'leg',
                          'value': s.first
                        }),
                  ),
                ]),
                const Text('leg B runs ~2.5% low, 6% hotter, glitchier',
                    style: TextStyle(color: Colors.white38, fontSize: 11)),
              ]),
        )),
        Card(
            child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            const Text('Chopper duty: '),
            Text(chop['duty'] ?? '—',
                style:
                    const TextStyle(fontFamily: 'monospace', fontSize: 16)),
            const Spacer(),
            FilledButton.tonal(
              onPressed: () => setNumRpc(context, widget.e,
                  'Chopper duty (0-1)', 'chopper', 'duty',
                  double.tryParse('${chop['duty']}') ?? 0.4),
              child: const Text('Set'),
            ),
          ]),
        )),
      ]),
    );
  }
}

// ------------------------------------------------------------------ MPS

class MpsPage extends StatefulWidget {
  const MpsPage({super.key, required this.e});
  final Epics e;
  @override
  State<MpsPage> createState() => _MpsPageState();
}

class _MpsPageState extends State<MpsPage> {
  List events = [];
  void _load() async {
    final r = await widget.e.rpc('events', {'n': 50});
    if (r is Map && r['events'] != null && mounted) {
      setState(() => events = r['events']);
    }
    Future.delayed(const Duration(seconds: 2), _load);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  Color _c(String k) => k == 'trip'
      ? kBad
      : k == 'reset' || k == 'armed'
          ? kOk
          : k == 'errant' || k == 'bpg' || k == 'source'
              ? kWarn
              : Colors.white54;

  @override
  Widget build(BuildContext context) {
    final permit = widget.e.scalar('PIP2:MPS:PERMIT') > 0.5;
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(children: [
        Card(
            color: permit ? const Color(0xFF11331E) : const Color(0xFF3A1414),
            child: Padding(
                padding: const EdgeInsets.all(12),
                child: Row(children: [
                  Icon(Icons.shield, color: permit ? kOk : kBad),
                  const SizedBox(width: 8),
                  Text(permit ? 'PERMIT ENABLED' : 'PERMIT INHIBITED',
                      style: const TextStyle(
                          fontSize: 16, fontWeight: FontWeight.bold)),
                  const Spacer(),
                  FilledButton.tonal(
                      onPressed: () => widget.e.rpc('mps_reset'),
                      child: const Text('RESET')),
                  const SizedBox(width: 6),
                  OutlinedButton(
                      onPressed: () => widget.e.rpc('rescue'),
                      child: const Text('RESCUE')),
                ]))),
        const SizedBox(height: 8),
        Expanded(
          child: Card(
            child: ListView.builder(
              itemCount: events.length,
              itemBuilder: (c, i) {
                final ev = events[i];
                return ListTile(
                  dense: true,
                  leading: Icon(Icons.circle,
                      size: 10, color: _c(ev['kind'])),
                  title: Text(ev['detail'],
                      style: const TextStyle(fontSize: 13)),
                  trailing: Text(ev['kind'],
                      style: TextStyle(color: _c(ev['kind']), fontSize: 11)),
                );
              },
            ),
          ),
        ),
      ]),
    );
  }
}

// ------------------------------------------------------------- snapshots

class SnapshotsPage extends StatefulWidget {
  const SnapshotsPage({super.key, required this.e});
  final Epics e;
  @override
  State<SnapshotsPage> createState() => _SnapshotsPageState();
}

class _SnapshotsPageState extends State<SnapshotsPage> {
  List names = [];
  void _load() async {
    final r = await widget.e.rpc('snapshots', {'action': 'list'});
    if (r is Map && r['names'] != null && mounted) {
      setState(() => names = r['names']);
    }
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(12),
        child: Column(children: [
          Row(children: [
            FilledButton.icon(
                onPressed: () async {
                  final ctl = TextEditingController();
                  final n = await showDialog<String>(
                      context: context,
                      builder: (c) => AlertDialog(
                            title: const Text('Save snapshot as'),
                            content: TextField(controller: ctl, autofocus: true),
                            actions: [
                              FilledButton(
                                  onPressed: () =>
                                      Navigator.pop(c, ctl.text),
                                  child: const Text('Save')),
                            ],
                          ));
                  if (n != null && n.isNotEmpty) {
                    await widget.e
                        .rpc('snapshots', {'action': 'save', 'name': n});
                    _load();
                  }
                },
                icon: const Icon(Icons.save),
                label: const Text('Save snapshot')),
            const SizedBox(width: 8),
            OutlinedButton.icon(
                onPressed: () =>
                    widget.e.rpc('snapshots', {'action': 'restore'}),
                icon: const Icon(Icons.restore),
                label: const Text('Restore golden (RESCUE)')),
          ]),
          const SizedBox(height: 8),
          Expanded(
            child: Card(
              child: ListView(children: [
                for (final n in names)
                  ListTile(dense: true, leading: const Icon(Icons.camera),
                      title: Text('$n')),
              ]),
            ),
          ),
        ]),
      );
}

// --------------------------------------------------------------- physics

class PhysicsPage extends StatefulWidget {
  const PhysicsPage({super.key, required this.e});
  final Epics e;
  @override
  State<PhysicsPage> createState() => _PhysicsPageState();
}

class _PhysicsPageState extends State<PhysicsPage> {
  Map phys = {};
  void _load() async {
    final r = await widget.e.rpc('phys');
    if (r is Map && mounted) setState(() => phys = r);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(12),
        child: Card(
          child: ListView(children: [
            const ListTile(
                title: Text('Physics engine parameters'),
                subtitle: Text('tap to override; RESCUE to reset')),
            for (final k in phys.keys)
              ListTile(
                dense: true,
                title: Text(k),
                trailing: Text('${phys[k]}',
                    style: const TextStyle(fontFamily: 'monospace')),
                onTap: () async {
                  final v = await promptNum(
                      context, k, double.tryParse('${phys[k]}') ?? 1.0);
                  if (v != null) {
                    await widget.e
                        .rpc('phys', {'set': true, 'field': k, 'value': v});
                    _load();
                  }
                },
              ),
          ]),
        ),
      );
}

// -------------------------------------------------------------- striptool

class StripToolPage extends StatefulWidget {
  const StripToolPage({super.key, required this.e});
  final Epics e;
  @override
  State<StripToolPage> createState() => _StripToolPageState();
}

class _StripToolPageState extends State<StripToolPage> {
  static const pvs = {
    'PIP2:BEAM:W': kAccent,
    'PIP2:BEAM:T': kOk,
    'PIP2:INJ:SCORE': kWarn,
  };
  final Map<String, Queue<double>> hist = {
    for (final p in pvs.keys) p: Queue<double>()
  };
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(milliseconds: 500), (_) {
      for (final p in pvs.keys) {
        final q = hist[p]!;
        q.add(widget.e.scalar(p));
        while (q.length > 600) q.removeFirst();
      }
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
            children: pvs.entries
                .map((e) => Expanded(
                    child: chartCard(
                        '${e.key}  (${widget.e.scalar(e.key).toStringAsFixed(3)})',
                        CustomPaint(
                            size: Size.infinite,
                            painter: SeriesPainter(
                                hist[e.key]!.toList(), e.value)))))
                .toList()),
      );
}

// --------------------------------------------------------------- profiles

class ProfilesPage extends StatefulWidget {
  const ProfilesPage({super.key, required this.e});
  final Epics e;
  @override
  State<ProfilesPage> createState() => _ProfilesPageState();
}

class _ProfilesPageState extends State<ProfilesPage> {
  Map scan = {}, alli = {};
  void _load() async {
    final s = await widget.e.rpc('scan_latest');
    final a = await widget.e.rpc('allison_latest');
    if (mounted) {
      setState(() {
        if (s is Map) scan = s;
        if (a is Map) alli = a;
      });
    }
    Future.delayed(const Duration(seconds: 1), _load);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final pos = (scan['pos'] as List?)?.cast<num>() ?? [];
    final ix = (scan['ix'] as List?)?.cast<num>() ?? [];
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(children: [
        Wrap(spacing: 8, children: [
          FilledButton(
              onPressed: () => widget.e.rpc('scan_request',
                  {'kind': 'wire', 'name': 'MEBT:WS1', 'points': 64}),
              child: const Text('Wire scan MEBT:WS1')),
          FilledButton(
              onPressed: () => widget.e.rpc('scan_request',
                  {'kind': 'laserwire', 'name': 'SSR2:LW1', 'points': 48}),
              child: const Text('Laserwire SSR2:LW1')),
          FilledButton(
              onPressed: () => widget.e.rpc('scan_request',
                  {'kind': 'laserwire', 'name': 'SSR2:LW1', 'halo': 1}),
              child: const Text('LW halo mode')),
          FilledButton(
              onPressed: () =>
                  widget.e.rpc('scan_request', {'kind': 'allison'}),
              child: const Text('Allison scan')),
        ]),
        const SizedBox(height: 8),
        Expanded(
            child: chartCard(
                'Profile scan: ${scan['name'] ?? '(idle)'} '
                '${(scan['done'] ?? 0) == 1.0 ? '✓' : ''}',
                CustomPaint(
                    size: Size.infinite,
                    painter: SeriesPainter(
                        ix.map((e) => e.toDouble()).toList(), kAccent,
                        bars: true, floor: 0)))),
        const SizedBox(height: 8),
        Card(
            child: ListTile(
                dense: true,
                title: const Text('Allison scanner (MEBT x-x′)'),
                trailing: Text(
                    'ε=${(alli['eps'] ?? 0).toStringAsFixed(3)} mm·mrad  '
                    'α=${(alli['alpha'] ?? 0).toStringAsFixed(2)}  '
                    'β=${(alli['beta'] ?? 0).toStringAsFixed(2)} m',
                    style: const TextStyle(fontFamily: 'monospace')))),
      ]),
    );
  }
}

// ---------------------------------------------------------- bunch monitor

class BunchPage extends StatefulWidget {
  const BunchPage({super.key, required this.e});
  final Epics e;
  @override
  State<BunchPage> createState() => _BunchPageState();
}

class _BunchPageState extends State<BunchPage> {
  Map w = {};
  void _load() async {
    final r = await widget.e.rpc('wcm_latest', {'name': 'MEBT:WCM1'});
    if (r is Map && mounted) setState(() => w = r);
    Future.delayed(const Duration(milliseconds: 800), _load);
  }

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final q = (w['q'] as List?)?.map((e) => (e as num).toDouble()).toList() ??
        <double>[];
    final bpg = (w['bpg'] as Map?) ?? {};
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(children: [
        Card(
            child: ListTile(
                dense: true,
                title: const Text('RWCM MEBT:WCM1 — bunch-by-bunch'),
                subtitle: Text(
                    'mode ${bpg['mode'] ?? '?'}  programmed duty '
                    '${bpg['programmed_duty'] ?? '?'}  measured '
                    '${bpg['measured_duty'] ?? '?'}  '
                    'σ ${(w['sig_ps'] ?? 0).toStringAsFixed(0)} ps'),
                trailing: Text(
                    (int.tryParse('${bpg['mismatch_buckets'] ?? 0}') ?? 0) == 0
                        ? '✓ verified'
                        : '✗ ${bpg['mismatch_buckets']} bad',
                    style: TextStyle(
                        color: (int.tryParse(
                                    '${bpg['mismatch_buckets'] ?? 0}') ??
                                0) ==
                            0
                            ? kOk
                            : kBad)))),
        const SizedBox(height: 8),
        Expanded(
            child: chartCard(
                'Bunch charge per 162.5 MHz bucket [nC]',
                CustomPaint(
                    size: Size.infinite,
                    painter:
                        SeriesPainter(q, const Color(0xFFFFD54F), bars: true, floor: 0)))),
      ]),
    );
  }
}

// ------------------------------------------------------- machine synoptic

class MachinePage extends StatefulWidget {
  const MachinePage({super.key, required this.e});
  final Epics e;
  @override
  State<MachinePage> createState() => _MachinePageState();
}

class _MachinePageState extends State<MachinePage> {
  Map geo = {};
  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() async {
    final r = await widget.e.rpc('geometry');
    if (r is Map && mounted) setState(() => geo = r);
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(12),
        child: chartCard(
            'Machine synoptic — floor plan, loss overlay',
            CustomPaint(
                size: Size.infinite,
                painter: MachinePainter(
                    geo, widget.e.array('PIP2:BLM:WPM')))),
      );
}

class MachinePainter extends CustomPainter {
  MachinePainter(this.geo, this.loss);
  final Map geo;
  final List<double> loss;
  @override
  void paint(Canvas canvas, Size size) {
    final poly = (geo['poly'] as List?) ?? [];
    final blm = (geo['blm_xy'] as List?) ?? [];
    if (poly.isEmpty) return;
    double minx = 1e9, maxx = -1e9, miny = 1e9, maxy = -1e9;
    for (final p in poly) {
      minx = math.min(minx, p[0]);
      maxx = math.max(maxx, p[0]);
      miny = math.min(miny, p[1]);
      maxy = math.max(maxy, p[1]);
    }
    final sx = size.width / (maxx - minx + 1);
    final sy = size.height / (maxy - miny + 20);
    final sc = math.min(sx, sy) * 0.9;
    Offset tp(num x, num y) => Offset(
        20 + (x - minx) * sc, size.height / 2 - (y - miny) * sc);
    final line = Paint()
      ..color = Colors.white54
      ..strokeWidth = 1.5
      ..style = PaintingStyle.stroke;
    final path = Path();
    for (var i = 0; i < poly.length; i++) {
      final o = tp(poly[i][0], poly[i][1]);
      i == 0 ? path.moveTo(o.dx, o.dy) : path.lineTo(o.dx, o.dy);
    }
    canvas.drawPath(path, line);
    for (var i = 0; i < blm.length; i++) {
      final w = i < loss.length ? loss[i] : 0.0;
      final o = tp(blm[i][0], blm[i][1]);
      final hot = (w / 20).clamp(0.0, 1.0);
      canvas.drawCircle(
          o,
          2 + hot * 5,
          Paint()
            ..color = Color.lerp(kOk, kBad, hot)!.withOpacity(0.85));
    }
  }

  @override
  bool shouldRepaint(covariant MachinePainter o) => true;
}

// ------------------------------------------------------------- training

class TrainingPage extends StatefulWidget {
  const TrainingPage({super.key, required this.e});
  final Epics e;
  @override
  State<TrainingPage> createState() => _TrainingPageState();
}

class _TrainingPageState extends State<TrainingPage> {
  List scen = [];
  @override
  void initState() {
    super.initState();
    widget.e.rpc('scenario', {'action': 'list'}).then((r) {
      if (r is Map && r['scenarios'] != null && mounted) {
        setState(() => scen = r['scenarios']);
      }
    });
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(12),
        child: Card(
          child: ListView(children: [
            const ListTile(
                title: Text('Training scenarios'),
                subtitle: Text(
                    'launch from the native GUI; browse the library here')),
            for (final s in scen)
              ListTile(
                dense: true,
                leading: Text(
                    {'easy': '★', 'medium': '★★', 'hard': '★★★'}[s['level']] ??
                        '',
                    style: const TextStyle(color: kWarn)),
                title: Text(s['name']),
                subtitle: Text(s['desc'],
                    style: const TextStyle(fontSize: 12)),
              ),
          ]),
        ),
      );
}

// ------------------------------------------------------------- helpers

Future<double?> promptNum(BuildContext c, String label, double cur) {
  final ctl = TextEditingController(text: cur.toStringAsFixed(3));
  return showDialog<double>(
      context: c,
      builder: (x) => AlertDialog(
            title: Text(label),
            content: TextField(
                controller: ctl,
                keyboardType: TextInputType.number,
                autofocus: true),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(x),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () =>
                      Navigator.pop(x, double.tryParse(ctl.text)),
                  child: const Text('Apply')),
            ],
          ));
}

void setNum(BuildContext c, Epics e, String label, String pv, double cur) async {
  final v = await promptNum(c, label, cur);
  if (v != null) e.put(pv, v);
}

void setNumRpc(BuildContext c, Epics e, String label, String cls, String field,
    double cur) async {
  final v = await promptNum(c, label, cur);
  if (v != null) e.rpc('set', {'cls': cls, 'field': field, 'value': v});
}
