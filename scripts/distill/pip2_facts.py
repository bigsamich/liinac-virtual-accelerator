"""Curated PIP-II accelerator facts for the fine-tune dataset.
Sources: PIP-II RDR/CDR, JACoW/arXiv papers, pip2.fnal.gov (research pack
docs/research/*). Each entry: (question, grounded answer)."""

FACTS = [
 ("What is PIP-II?",
  "PIP-II (Proton Improvement Plan II) is Fermilab's 800 MeV H- "
  "superconducting linac, about 215 m long, feeding the Booster to enable "
  ">1 MW beam power for LBNF/DUNE. It runs 0.55 ms pulses at 20 Hz "
  "(1.1% duty) with 2 mA average delivered to the Booster, and is built "
  "CW-capable for future MW-class programs like Mu2e-II."),
 ("Describe the PIP-II acceleration chain.",
  "H- ions start at a 30 keV ion source into the LEBT, a 162.5 MHz 4-vane "
  "RFQ (4.45 m) accelerates to 2.1 MeV CW, the MEBT with a bunch-by-bunch "
  "chopper shapes the Booster injection pattern, then the SC linac: HWR "
  "(162.5 MHz) 2.1->10 MeV, SSR1 (325 MHz) to ~35 MeV, SSR2 (325 MHz) to "
  "185 MeV, LB650 and HB650 (650 MHz ellipticals) to 800 MeV, then the "
  "Beam Transfer Line to the Booster."),
 ("How many cryomodules and cavities does PIP-II have?",
  "23 cryomodules of five types: 1 HWR (8 half-wave resonators), 2 SSR1 "
  "cryomodules of 8 cavities each (16), 7 SSR2 cryomodules of 5 each "
  "(35), plus 13 cryomodules of 650 MHz elliptical 5-cell cavities (LB650 "
  "and HB650). The LLRF system controls about 125 cavities in total "
  "including the RFQ and bunchers."),
 ("Why is the RFQ output energy 2.1 MeV?",
  "2.1 MeV is below the neutron-production threshold of most materials, "
  "simplifying RFQ/MEBT maintenance and activation control; it also "
  "balances space-charge against adiabatic bunching quality."),
 ("Why is the ion source at 30 keV?",
  "30 keV is a compromise: higher energy worsens the RFQ's adiabatic "
  "bunching (longitudinal emittance), lower energy increases space-charge "
  "driven transverse emittance growth in the LEBT."),
 ("What are the design emittances out of the front end?",
  "At nominal current the RFQ delivers about 0.15 mm-mrad rms normalized "
  "transverse emittance and 0.7 keV-ns (~0.22 mm-mrad) longitudinal."),
 ("How does Booster injection work?",
  "Charge-exchange injection: a thin carbon stripping foil removes both "
  "electrons from the 800 MeV H- beam so it merges with the circulating "
  "proton beam. One 0.55 ms linac pulse paints about 285 Booster turns, "
  "with transverse painting to spread space charge and minimize foil "
  "hits. The MEBT chopper pre-shapes the bunch pattern to match the "
  "Booster RF buckets and leaves an extraction-kicker notch."),
 ("What are the LLRF field stability requirements?",
  "0.065% in amplitude and 0.065 degrees in phase class, across ~125 "
  "cavities. In pulsed mode a gated feedforward synchronized to the beam "
  "is essential; PIP2IT demonstrated 0.008-0.029% amplitude and "
  "0.01-0.06 degree phase stability."),
 ("What frequencies does PIP-II use?",
  "Three RF frequency families: 162.5 MHz (RFQ, MEBT bunchers, HWR), "
  "325 MHz (SSR1, SSR2 single-spoke resonators), and 650 MHz (LB650, "
  "HB650 elliptical cavities). The bunch structure is 162.5 MHz — one "
  "bucket every 6.15 ns."),
 ("What is the CW upgrade path?",
  "The cavities, cryomodules and RF are all CW-capable by design; the "
  "cryoplant capacity is the main pulsed-mode limitation. Upgrading "
  "cryogenics enables CW operation for MW-class experiments (e.g. "
  "Mu2e-II) without rebuilding the linac."),
 ("What cryogenic temperature levels does PIP-II use?",
  "Three: 40 K thermal shields, 4.5 K intercepts/coupler cooling, and "
  "2 K (superfluid, ~31 mbar saturated) for the SRF cavities. He bath "
  "pressure stability matters because cavity df/dp is a few Hz/mbar "
  "(SSR2 measured -3.2 to -3.6 Hz/mbar)."),
 ("What diagnostics does the PIP-II linac use?",
  "About 126 BPMs (button pickups, also giving phase/TOF energy), "
  "toroids/BCMs for current, resistive wall current monitors for "
  "bunch-by-bunch structure and chopper extinction (1e-4 demonstrated at "
  "PIP2IT), wire scanners in the warm front end, laserwire "
  "(H- photodetachment) profile stations along the SC linac (12 "
  "stations), BLMs for machine protection, and Fast Faraday Cups for "
  "bunch length."),
 ("Why laserwires instead of wire scanners in the SC linac?",
  "H- photodetachment is non-invasive: a focused laser (<100 um rms) "
  "strips the outer electron and the electrons are collected downstream, "
  "so profiles can be measured at full beam power where a physical wire "
  "would melt and would load the SRF cavities with scattered particles."),
 ("What is the MEBT chopper for?",
  "It removes individual 162.5 MHz bunches in an arbitrary programmable "
  "pattern so the beam injected into the Booster matches its RF bucket "
  "structure and leaves a clean extraction gap; nominal operation keeps "
  "roughly 40-44% of bunches. Chopped bunches must be extinguished to "
  "the 1e-4 level."),
 ("Who builds PIP-II?",
  "Fermilab with major international in-kind partners including India "
  "(DAE labs), Italy (INFN), France (CEA/IN2P3), the UK (STFC/UKRI) and "
  "Poland — the first US accelerator built with significant "
  "international contributions."),
 ("What beam current does the linac run?",
  "The source/RFQ deliver up to 10 mA CW capability with 5 mA nominal "
  "pre-chop; after the MEBT chopper the delivered average is 2 mA at "
  "800 MeV during the 0.55 ms pulse."),
 ("What are typical SRF gradients in PIP-II?",
  "The 650 MHz elliptical cavities run around 17-19 MV/m accelerating "
  "gradient class; spoke resonators run lower voltage per cavity "
  "(HWR ~2 MV/cavity class, SSR1/SSR2 few-MV class) matched to the "
  "increasing beta profile."),
]
