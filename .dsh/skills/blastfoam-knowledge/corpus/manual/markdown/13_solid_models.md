# 13 Solid models

A port of solids4foam has been incorporated into the blastFSI solver. These models allow for linear and non-linear deformation using the finite-volume methodolgy described in Cardiff et al. (2018); Cardiff and Demirdzic (2021) and Simo and Hughes (2000) for plasticity.

In addition, if solids4foam is available locally, the blastSolids4Foam library can also be compiled to allow use of the models available in the blastFoam solver to be used with solids4Foam solver by specifying the blast fluid.

> **NOTE:** These models are still under development and have not been extensively validated specifically for blast.
