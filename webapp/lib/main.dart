// PIP-II VA console — Flutter web control room over the EPICS web gateway.
import 'package:flutter/material.dart';

import 'epics.dart';
import 'pages.dart';

void main() => runApp(const Pip2App());

class Pip2App extends StatefulWidget {
  const Pip2App({super.key});
  @override
  State<Pip2App> createState() => _Pip2AppState();
}

class _Pip2AppState extends State<Pip2App> {
  late final Epics e;
  int page = 0;

  static const nav = [
    (Icons.dashboard, 'Status'),
    (Icons.show_chart, 'Orbit'),
    (Icons.warning_amber, 'Losses'),
    (Icons.settings_input_antenna, 'RF'),
    (Icons.tune, 'Magnets'),
    (Icons.opacity, 'Vacuum'),
    (Icons.science, 'Studies'),
    (Icons.smart_toy, 'Ask'),
  ];

  @override
  void initState() {
    super.initState();
    final loc = Uri.base;
    final scheme = loc.scheme == 'https' ? 'wss' : 'ws';
    e = Epics('$scheme://${loc.authority}/ws');
    e.subscribe(const [
      'PIP2:BEAM:W', 'PIP2:BEAM:T', 'PIP2:BEAM:IOUT', 'PIP2:BEAM:PULSE',
      'PIP2:MPS:PERMIT', 'PIP2:BPM:X', 'PIP2:BPM:Y', 'PIP2:BLM:WPM',
      'PIP2:BCM:I_MA', 'PIP2:VAC:TORR', 'PIP2:INJ:SCORE',
      'PIP2:RF:DETUNING_HZ', 'PIP2:MAG:VALUES',
    ]);
  }

  Widget _body() {
    switch (page) {
      case 0:
        return DashboardPage(e: e);
      case 1:
        return ArrayPage(e, 'Orbit x/y [mm] — 108 BPMs', 'PIP2:BPM:X',
            pv2: 'PIP2:BPM:Y', symmetric: true);
      case 2:
        return ArrayPage(e, 'Beam loss [W/m] — 120 BLMs', 'PIP2:BLM:WPM',
            bars: true, color: kBad);
      case 3:
        return RfPage(e: e);
      case 4:
        return ArrayPage(e, 'Magnet readbacks [A]', 'PIP2:MAG:VALUES',
            symmetric: true, color: kAccent);
      case 5:
        return UtilitiesPage(e: e);
      case 6:
        return StudiesPage(e: e);
      default:
        return AskPage(e: e);
    }
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
          final wide = MediaQuery.of(context).size.width > 720;
          if (wide) {
            return Scaffold(
              body: Row(children: [
                NavigationRail(
                  selectedIndex: page,
                  onDestinationSelected: (i) => setState(() => page = i),
                  backgroundColor: kCard,
                  labelType: NavigationRailLabelType.all,
                  destinations: [
                    for (final n in nav)
                      NavigationRailDestination(
                          icon: Icon(n.$1), label: Text(n.$2)),
                  ],
                ),
                Expanded(child: _body()),
              ]),
            );
          }
          return Scaffold(
            body: SafeArea(child: _body()),
            bottomNavigationBar: NavigationBar(
              selectedIndex: page,
              onDestinationSelected: (i) => setState(() => page = i),
              backgroundColor: kCard,
              destinations: [
                for (final n in nav)
                  NavigationDestination(icon: Icon(n.$1), label: n.$2),
              ],
            ),
          );
        },
      ),
    );
  }
}
