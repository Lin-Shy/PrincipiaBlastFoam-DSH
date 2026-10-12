# Turbulence

In addition to the hyperbolic flux terms, viscous effects can be included in simulations. This includes the use of turbulence models such as Reynolds averaged Navier-Stokes (RANS) or Large Eddy simulations (LES) models. All single phase turbulence models standard to OpenFOAM including k-epsilon, k-omega, Smagorinsky, as well as many others are available. The specified model introduces additional transport equations, as well as modifications to transport coefficients like viscosity ($\nu$) and thermal diffusivity ($\alpha$) which modify the viscous terms in the conservation equations. When the maximum viscosity is zero, the constant/momentumTransport (or constant/turbulenceProperties) does not need to be included, however if any phase has viscous terms, this dictionary needs to be included along with the appropriate turbulence model (laminar is the same as no turbulence model). The available turbulence models are listed below, and these can also be found using the '-listMomentumTransportModels' option when running blastFoam.

Turbulence models: LES, RAS, laminar (e.g. no model)

laminar models:

- Giesekus
- Maxwell
- Stokes (default)
- generalizedNewtonian

RAS models:

- LRR
- LaunderSharmaKE
- RNGkEpsilon
- SSG
- SpalartAllmaras
- buoyantKEpsilon
- kEpsilon
- kOmega
- kOmega2006
- kOmegaSST
- kOmegaSSTLM
- kOmegaSSTSAS
- realizableKE
- v2f

LES models:

- DeardorffDiffStress
- Smagorinsky
- SpalartAllmarasDDES
- SpalartAllmarasDES
- SpalartAllmarasIDDES
- WALE
- dynamicKEqn
- dynamicLagrangian
- kEqn
- kOmegaSSTDES

> **NOTE:** Many of the turbulence models require additional field (k, epsilon, omega, etc.) to be specified in the initial conditions folder.
