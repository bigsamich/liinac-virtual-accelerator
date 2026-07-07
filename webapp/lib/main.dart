// PIP-II VA console — Flutter web control room over the EPICS web gateway.
import 'package:flutter/material.dart';

import 'epics.dart';
import 'pages.dart';
import 'pages2.dart';
import 'scene3d.dart';

void main() => runApp(const Pip2App());

class Pip2App extends StatefulWidget {
  const Pip2App({super.key});
  @override
  State<Pip2App> createState() => _Pip2AppState();
}

class _Pip2AppState extends State<Pip2App> {
  late final Epics e;
  int page = 0;

  late final List<(String, IconData, Widget Function())> pages = [
    ('Dashboard', Icons.dashboard, () => DashboardPage(e: e)),
    ('3D machine', Icons.threed_rotation, () => Machine3DPage(e: e)),
    ('Orbit', Icons.show_chart,
        () => ArrayPage(e, 'Orbit x/y [mm] — 108 BPMs', 'PIP2:BPM:X',
            pv2: 'PIP2:BPM:Y', symmetric: true)),
    ('Losses', Icons.warning_amber,
        () => ArrayPage(e, 'Beam loss [W/m] — 120 BLMs', 'PIP2:BLM:WPM',
            bars: true, color: kBad)),
    ('Profiles', Icons.blur_on, () => ProfilesPage(e: e)),
    ('Beam spot 3D', Icons.lens_blur, () => Profile3DPage(e: e)),
    ('Bunch monitor', Icons.graphic_eq, () => BunchPage(e: e)),
    ('Strip tool', Icons.timeline, () => StripToolPage(e: e)),
    ('RF', Icons.settings_input_antenna,
        () => DeviceTablePage(e: e, cls: 'rf', title: 'RF cavities')),
    ('Magnets', Icons.tune,
        () => DeviceTablePage(e: e, cls: 'magnet', title: 'Magnets')),
    ('Source & LEBT', Icons.wb_incandescent, () => SourcePage(e: e)),
    ('Vacuum', Icons.opacity, () => UtilitiesPage(e: e)),
    ('MPS', Icons.shield, () => MpsPage(e: e)),
    ('Snapshots', Icons.camera_alt, () => SnapshotsPage(e: e)),
    ('Physics', Icons.functions, () => PhysicsPage(e: e)),
    ('Studies', Icons.science, () => StudiesPage(e: e)),
    ('Training', Icons.school, () => TrainingPage(e: e)),
    ('Ask', Icons.smart_toy, () => AskPage(e: e)),
  ];

  @override
  void initState() {
    super.initState();
    final loc = Uri.base;
    final pp = int.tryParse(loc.queryParameters['p'] ?? '');
    if (pp != null && pp >= 0 && pp < pages.length) page = pp;
    final scheme = loc.scheme == 'https' ? 'wss' : 'ws';
    e = Epics('$scheme://${loc.authority}/ws');
    e.subscribe(const [
      'PIP2:BEAM:W', 'PIP2:BEAM:T', 'PIP2:BEAM:IOUT', 'PIP2:BEAM:PULSE',
      'PIP2:BEAM:LAG', 'PIP2:MPS:PERMIT', 'PIP2:BPM:X', 'PIP2:BPM:Y',
      'PIP2:BLM:WPM', 'PIP2:BCM:I_MA', 'PIP2:VAC:TORR', 'PIP2:INJ:SCORE',
      'PIP2:RF:DETUNING_HZ', 'PIP2:MAG:VALUES',
    ]);
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PIP-II VA',
      debugShowCheckedModeBanner: false,
      theme: ThemeData.dark(useMaterial3: true)
          .copyWith(scaffoldBackgroundColor: kBg, cardColor: kCard),
      home: AnimatedBuilder(
        animation: e,
        builder: (context, _) {
          final permit = e.scalar('PIP2:MPS:PERMIT') > 0.5;
          return Scaffold(
            appBar: AppBar(
              backgroundColor: kCard,
              title: Row(children: [
                Text(pages[page].$1),
                const Spacer(),
                Text('${e.scalar('PIP2:BEAM:W').toStringAsFixed(0)} MeV  '
                    '${(100 * e.scalar('PIP2:BEAM:T')).toStringAsFixed(1)}%',
                    style: const TextStyle(fontSize: 14)),
                const SizedBox(width: 10),
                Icon(Icons.circle,
                    size: 12, color: permit ? kOk : kBad),
                const SizedBox(width: 4),
                Icon(Icons.wifi,
                    size: 14, color: e.connected ? kOk : kBad),
              ]),
            ),
            drawer: Drawer(
              backgroundColor: kCard,
              child: ListView(children: [
                const DrawerHeader(
                    child: Center(
                        child: Text('PIP-II\nVirtual Accelerator',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                                fontSize: 20, fontWeight: FontWeight.bold)))),
                for (var i = 0; i < pages.length; i++)
                  ListTile(
                    dense: true,
                    selected: i == page,
                    leading: Icon(pages[i].$2),
                    title: Text(pages[i].$1),
                    onTap: () {
                      setState(() => page = i);
                      Navigator.pop(context);
                    },
                  ),
              ]),
            ),
            body: pages[page].$3(),
          );
        },
      ),
    );
  }
}
