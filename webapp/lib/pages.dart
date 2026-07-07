// PIP-II VA console pages — parity build with the Python control room.
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'epics.dart';

Widget bigValue(String label, String v, String unit, Color c) => Expanded(
    child: Card(
        child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(children: [
              Text(label,
                  style: const TextStyle(color: Colors.white54, fontSize: 12)),
              FittedBox(
                  child: Text(v,
                      style: TextStyle(
                          fontSize: 30,
                          fontWeight: FontWeight.bold,
                          color: c))),
              Text(unit, style: const TextStyle(color: Colors.white38)),
            ]))));

// ------------------------------------------------------------- dashboard

class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key, required this.e});
  final Epics e;
  @override
  Widget build(BuildContext context) {
    final permit = e.scalar('PIP2:MPS:PERMIT') > 0.5;
    final t = e.scalar('PIP2:BEAM:T');
    final inj = e.scalar('PIP2:INJ:SCORE');
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Card(
          color: permit ? const Color(0xFF11331E) : const Color(0xFF3A1414),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Icon(Icons.circle, color: permit ? kOk : kBad, size: 16),
              const SizedBox(width: 8),
              Expanded(
                  child: Text(
                      permit
                          ? 'BEAM PERMIT: ENABLED'
                          : 'BEAM PERMIT: INHIBITED',
                      style: const TextStyle(
                          fontSize: 17, fontWeight: FontWeight.bold))),
              FilledButton.tonal(
                  onPressed: () => e.rpc('mps_reset'),
                  child: const Text('RESET')),
              const SizedBox(width: 6),
              OutlinedButton(
                  onPressed: () => e.rpc('rescue'),
                  child: const Text('RESCUE')),
              const SizedBox(width: 8),
              Icon(Icons.circle,
                  size: 10, color: e.connected ? kOk : kBad),
            ]),
          ),
        ),
        const SizedBox(height: 10),
        Row(children: [
          bigValue('Energy', e.scalar('PIP2:BEAM:W').toStringAsFixed(1), 'MeV',
              kAccent),
          bigValue('Transmission', (100 * t).toStringAsFixed(2), '%',
              t > 0.95 ? kOk : kBad),
          bigValue('Delivered', e.scalar('PIP2:BEAM:IOUT').toStringAsFixed(3),
              'mA', kAccent),
          bigValue('Injection η', inj.toStringAsFixed(1), 'score',
              inj > 80 ? kOk : kWarn),
        ]),
        const SizedBox(height: 10),
        Expanded(
          child: Row(children: [
            Expanded(
                child: chartCard(
                    'BCM current [mA]',
                    CustomPaint(
                        size: Size.infinite,
                        painter: SeriesPainter(e.array('PIP2:BCM:I_MA'), kOk,
                            bars: true, floor: 0)))),
            const SizedBox(width: 8),
            Expanded(
                child: chartCard(
                    'Beam loss [W/m]',
                    CustomPaint(
                        size: Size.infinite,
                        painter: SeriesPainter(e.array('PIP2:BLM:WPM'), kBad,
                            bars: true, floor: 0)))),
            const SizedBox(width: 8),
            Expanded(
                child: chartCard(
                    'Orbit x/y [mm]',
                    CustomPaint(
                        size: Size.infinite,
                        painter: SeriesPainter(e.array('PIP2:BPM:X'), kAccent,
                            data2: e.array('PIP2:BPM:Y'),
                            color2: kWarn,
                            symmetric: true)))),
          ]),
        ),
      ]),
    );
  }
}

// ----------------------------------------------------- generic array page

class ArrayPage extends StatelessWidget {
  const ArrayPage(this.e, this.title, this.pv,
      {super.key,
      this.pv2,
      this.bars = false,
      this.symmetric = false,
      this.color = kAccent});
  final Epics e;
  final String title, pv;
  final String? pv2;
  final bool bars, symmetric;
  final Color color;
  @override
  Widget build(BuildContext context) => Padding(
      padding: const EdgeInsets.all(12),
      child: chartCard(
          title,
          CustomPaint(
              size: Size.infinite,
              painter: SeriesPainter(e.array(pv), color,
                  data2: pv2 == null ? null : e.array(pv2!),
                  color2: kWarn,
                  bars: bars,
                  symmetric: symmetric,
                  floor: bars ? 0 : null))));
}

// -------------------------------------------------------------- RF page

class RfPage extends StatelessWidget {
  const RfPage({super.key, required this.e});
  final Epics e;
  // display name -> official PV base
  static const cavs = [
    ['HWR CAV4', 'LSCL:HWR-1_LLRF_CAV1104'],
    ['SSR1 CAV11', 'LSCL:SSR1-2_LLRF_CAV2203'],
    ['SSR2 CAV17', 'LSCL:SSR2-4_LLRF_CAV3402'],
    ['LB650 CAV22', 'LSCL:LB-6_LLRF_CAV4602'],
    ['HB650 CAV12', 'LSCL:HB-2_LLRF_CAV5206'],
    ['HB650 CAV36', 'LSCL:HB-6_LLRF_CAV5606'],
  ];
  @override
  Widget build(BuildContext context) {
    for (final c in cavs) {
      e.subscribe(['${c[1]}:AMPL', '${c[1]}:PHS', '${c[1]}:DET']);
    }
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(children: [
        SizedBox(
            height: 150,
            child: chartCard(
                'All cavity detuning [Hz]',
                CustomPaint(
                    size: Size.infinite,
                    painter: SeriesPainter(
                        e.array('PIP2:RF:DETUNING_HZ'), kWarn,
                        symmetric: true)))),
        const SizedBox(height: 8),
        Expanded(
          child: Card(
            child: ListView(children: [
              const ListTile(
                  dense: true,
                  title: Text('RF cavities — official ED0011740 PVs'),
                  subtitle: Text('tap a row to set phase')),
              for (final c in cavs)
                ListTile(
                  dense: true,
                  title: Text(c[0]),
                  subtitle: Text(c[1],
                      style: const TextStyle(
                          color: Colors.white38, fontSize: 10)),
                  trailing: Text(
                      '${e.scalar('${c[1]}:AMPL').toStringAsFixed(2)} MV  '
                      '${e.scalar('${c[1]}:PHS').toStringAsFixed(1)}°  '
                      '${e.scalar('${c[1]}:DET').toStringAsFixed(0)} Hz',
                      style: const TextStyle(fontFamily: 'monospace')),
                  onTap: () => _setNum(context, e, '${c[0]} phase [deg]',
                      '${c[1]}:sPHS', e.scalar('${c[1]}:PHS')),
                ),
            ]),
          ),
        ),
      ]),
    );
  }
}

// ---------------------------------------------------------- utilities

class UtilitiesPage extends StatelessWidget {
  const UtilitiesPage({super.key, required this.e});
  final Epics e;
  @override
  Widget build(BuildContext context) {
    final vac = e
        .array('PIP2:VAC:TORR')
        .map((p) => p > 0 ? math.log(p) / math.ln10 : -10.0)
        .toList();
    return Padding(
      padding: const EdgeInsets.all(12),
      child: Column(children: [
        Expanded(
            child: chartCard(
                'Vacuum log10(P) [torr] — 40 gauges',
                CustomPaint(
                    size: Size.infinite,
                    painter: SeriesPainter(vac, const Color(0xFFBA68C8),
                        bars: true)))),
        const SizedBox(height: 8),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Row(children: [
              const Text('Inject leak — gauge '),
              SizedBox(
                  width: 120,
                  child: _NumField(
                      hint: '0-39',
                      onSet: (v) => e.put('PIP2:VAC:sLEAK_GAUGE', v))),
              const SizedBox(width: 12),
              const Text('size [e-7 torr] '),
              SizedBox(
                  width: 120,
                  child: _NumField(
                      hint: '0-99',
                      onSet: (v) => e.put('PIP2:VAC:sLEAK_TORR', v * 1e-7))),
              const Spacer(),
              OutlinedButton(
                  onPressed: () => e.put('PIP2:VAC:sLEAK_TORR', 0),
                  child: const Text('Clear leak')),
            ]),
          ),
        ),
      ]),
    );
  }
}

// ----------------------------------------------------------- studies

class StudiesPage extends StatefulWidget {
  const StudiesPage({super.key, required this.e});
  final Epics e;
  @override
  State<StudiesPage> createState() => _StudiesPageState();
}

class _StudiesPageState extends State<StudiesPage> {
  Map<String, dynamic> st = {};
  final _nl = TextEditingController();
  String msg = '';

  @override
  void initState() {
    super.initState();
    _poll();
  }

  void _poll() async {
    if (!mounted) return;
    final r = await widget.e.rpc('study_state');
    if (mounted && r is Map) setState(() => st = Map.from(r));
    Future.delayed(const Duration(seconds: 3), _poll);
  }

  @override
  Widget build(BuildContext context) {
    final running = st['running'];
    final queue = (st['queue'] as List?) ?? [];
    final presets = (st['presets'] as List?) ?? [];
    return Padding(
      padding: const EdgeInsets.all(12),
      child: ListView(children: [
        Card(
            child: ListTile(
          title: Text(running == null
              ? 'No study running'
              : '▶ ${running['name']} — ${running['status']}  '
                  '(${running['step']}/${running['total']})',
              style: TextStyle(color: running == null ? Colors.white54 : kOk)),
          trailing: Wrap(spacing: 6, children: [
            FilledButton.tonal(
                onPressed: () async {
                  final r = await widget.e.rpc('run_next');
                  setState(() => msg = _m(r));
                },
                child: const Text('Run next')),
            OutlinedButton(
                onPressed: () => widget.e.rpc('abort'),
                child: const Text('Abort')),
          ]),
        )),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Plan with AI'),
                  const SizedBox(height: 6),
                  TextField(
                      controller: _nl,
                      decoration: const InputDecoration(
                          isDense: true,
                          border: OutlineInputBorder(),
                          hintText:
                              'e.g. sweep SSR1:CAV11 phase ±5°, 9 steps')),
                  const SizedBox(height: 6),
                  Align(
                    alignment: Alignment.centerRight,
                    child: FilledButton(
                        onPressed: () async {
                          setState(() => msg = 'planning…');
                          final r = await widget.e
                              .rpc('plan', {'text': _nl.text});
                          if (r is Map && r['plan'] != null) {
                            final q = await widget.e
                                .rpc('queue_plan', {'plan': r['plan']});
                            setState(() => msg = 'queued ${_m(q)}');
                          } else {
                            setState(() => msg = _m(r));
                          }
                        },
                        child: const Text('Plan & queue')),
                  ),
                ]),
          ),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text('Presets (tap to queue)'),
                  const SizedBox(height: 6),
                  Wrap(spacing: 6, runSpacing: 6, children: [
                    for (final p in presets)
                      ActionChip(
                          label: Text(p as String,
                              style: const TextStyle(fontSize: 11)),
                          onPressed: () async {
                            final r = await widget.e
                                .rpc('queue_preset', {'name': p});
                            setState(() => msg = _m(r));
                          }),
                  ]),
                ]),
          ),
        ),
        Card(
            child: Padding(
                padding: const EdgeInsets.all(10),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Queue (${queue.length})'),
                      const SizedBox(height: 4),
                      for (final q in queue)
                        Text('• $q',
                            style: const TextStyle(
                                color: Colors.white70, fontSize: 13)),
                    ]))),
        if (msg.isNotEmpty)
          Padding(
              padding: const EdgeInsets.all(6),
              child: Text(msg, style: const TextStyle(color: kAccent))),
      ]),
    );
  }

  String _m(dynamic r) {
    if (r is Map) {
      if (r['error'] != null) return '✗ ${r['error']}';
      return '✓ ${r['queued'] ?? r['started'] ?? 'ok'}';
    }
    return '$r';
  }
}

// ------------------------------------------------------------- ask page

class AskPage extends StatefulWidget {
  const AskPage({super.key, required this.e});
  final Epics e;
  @override
  State<AskPage> createState() => _AskPageState();
}

class _AskPageState extends State<AskPage> {
  final _q = TextEditingController();
  String ans = '';
  bool busy = false;

  void _ask() async {
    if (_q.text.trim().isEmpty) return;
    setState(() {
      busy = true;
      ans = 'thinking…';
    });
    final r = await widget.e.rpc('ask', {'q': _q.text});
    setState(() {
      busy = false;
      ans = r is Map
          ? '[${r['engine']}] ${r['answer'] ?? r['error']}'
          : '$r';
    });
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.all(12),
        child: Column(children: [
          Row(children: [
            Expanded(
                child: TextField(
                    controller: _q,
                    onSubmitted: (_) => _ask(),
                    decoration: const InputDecoration(
                        border: OutlineInputBorder(),
                        isDense: true,
                        hintText:
                            'Ask the machine… (status? what if I raise to 6 mA?)'))),
            const SizedBox(width: 8),
            FilledButton(
                onPressed: busy ? null : _ask,
                child: Text(busy ? 'Asking…' : 'Ask')),
          ]),
          const SizedBox(height: 12),
          Expanded(
              child: Card(
                  child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: SingleChildScrollView(
                          child: Text(ans,
                              style: const TextStyle(
                                  fontSize: 15, height: 1.4)))))),
        ]),
      );
}

// ----------------------------------------------------------- helpers

Future<void> _setNum(BuildContext context, Epics e, String label, String pv,
    double cur) async {
  final ctl = TextEditingController(text: cur.toStringAsFixed(2));
  final v = await showDialog<double>(
      context: context,
      builder: (c) => AlertDialog(
            title: Text(label),
            content: TextField(
                controller: ctl,
                keyboardType: TextInputType.number,
                autofocus: true),
            actions: [
              TextButton(
                  onPressed: () => Navigator.pop(c),
                  child: const Text('Cancel')),
              FilledButton(
                  onPressed: () => Navigator.pop(c, double.tryParse(ctl.text)),
                  child: const Text('Apply')),
            ],
          ));
  if (v != null) e.put(pv, v);
}

class _NumField extends StatelessWidget {
  const _NumField({required this.hint, required this.onSet});
  final String hint;
  final void Function(double) onSet;
  @override
  Widget build(BuildContext context) {
    final c = TextEditingController();
    return TextField(
        controller: c,
        keyboardType: TextInputType.number,
        onSubmitted: (t) {
          final v = double.tryParse(t);
          if (v != null) onSet(v);
        },
        decoration: InputDecoration(
            isDense: true, border: const OutlineInputBorder(), hintText: hint));
  }
}
