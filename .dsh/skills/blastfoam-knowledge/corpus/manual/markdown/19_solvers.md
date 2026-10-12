# 19 Solvers

blastFoam offers a wide variety of solvers for simulating transient, highly compressible flows. A short description of each is given below.

## 19.1 blastFoam

The blastFoam solver is the standard solver and has a variety of uses, including single phase, two phase and multiphase flows, where the phases and thermodynamic models are specified in the constant/phaseProperties. When a list of phases is provided (and the list has more than one entry), the two phase or multiphase solver is selected. If the key word phases is not specified, then the single phase solver is selected. All phases use the blastFoam specific equations of states (see Section 5).

## 19.2 blastEulerFoam

The blastEulerFoam solver is the Euler-Euler (two/multifluid) variant of blastFoam. Currently only fluid-solid simulations are supported; however, the addition of fluid-fluid simulations is under development. This solver is based on the work of Houim and Oran (2016) and Lai et al. (2018). One major advantage over the standard multiphaseEulerFoam solver is that any number of particle phases can be used. Currently there are three phase models that can be used: fluid, multiphase, and granular. The fluid phase model is used to describe a single component fluid (such as air). The multiphase phase model is used to describe a fluid phase consisting of multiple phases, each described by a unique equation of state. This allows simulations of standard detonation problems with the addition of particles. The granular phase model is used to describe a solid phase. Both the fluid and multiphase models can use any of the fluid thermodynamic models, while the granular model can use any of the solid thermodynamic models. The models describing interactions between fluids are described in Sec. 3 and Sec. 4

> **NOTE:** While multiple fluid phases will not cause the solver to fail, theses types of simulations are not currently supported.

## 19.3 blastFSIFoam

The blastFSIFoam solver uses the standard blastFoam solver to solve the fluid phase, and the models mentioned in Sec. 13 to handle the solid deformation. The fluid phase uses a moving mesh, while the solid phase can be solved using a total lagrangian or linear (stationary), or updated Lagrangian (moving) method. In order to correctly transfer the information between the patches, the coupledGlobalPolyPatch Cardiff et al. (2018) is used and does not require any changed to the mesh patch types. Fields that require coupling information (temperature, displacment, etc.) should used a global patch type (see Sec. 8.1). If meshes are made for each individual region, the patch types can be specified as usual. However, if the splitMeshRegions utility is used to separate a single region mesh into multiple region meshes, the patch names and types may need to be modified

> **NOTE:** This solver is still in development. Please use with caution.

## 19.4 blastXiFoam (Experimental)

In addition to the standard blastFoam solver, an additional solver has been added to solve combustion as an extension of the standard OpenFOAM Xi-Foam solver. The only difference is that the flux schemes presented earlier are used to transport the conserved quantities. This allows for a more accurate description of combusting, highly compressible flows (i.e. deflagration to detonation transition). It is recommended to use the adibaticFlameT utility to calculate the model coefficients used in the required constant/thermophysicalProperties dictionary.

## 19.5 blastReactingFoam (Experimental)

blastReactingFoam uses the standard OpenFOAM thermodynamic classes, and can be used to solve multi-specie systems that include reactions. The use of combustion models are also available. The constant/thermophysicalProperties dictionary must be included under the constant dictionary along with the relevant dictionaries (constant/combustionProperties and constant/chemistyProperties) and initial value files (mass fractions). The conserved quantities (mass, momentum, and energy) as well as the mass fractions are all transported using the flux schemes presented herein.

## 19.6 blastMultiRegionFoam (Experimental)

The blastMultiRegionFoam solver is derived from the chtMultiRegionFoam available in OpenFOAM. The major differences are in the use of ODE time integration and Riemann fluxes. The thermal transport in solids is still treated implicitly through a matrix solution.

## 19.7 blastParcelFoam (Experimental)

blastParcelFoam makes use of the standard OpenFOAM Lagrangian classes to solve a coupled Eulerian fluid and collection of Lagragian parcels. This includes interaction terms like drag, heat transfer, and particle collisions. Not all of the OpenFOAM standard Lagrangian options are available due to the use of a different thermodynamic model. While AMR can be used, dynamic load balancing cannot.

## 19.8 blastEquation

blastEquation makes use of the numerics library and can be used to interrogate simple equations, or more complicated, coded function evaluations. This utility can either be used strictly though the command line, or using dictionaries to define equations and the operations they are used with. More control is available when using dictionaries, specifically with respect to root solving, minimization, and integration schemes. Please see tutorials/blastEquation for more complete examples on how to use this utility.

| Entry | Description |
|---|---|
| -func | Dictionary used to define the equation |
| -dict | Dictionary used to define operations on the equation |
| -clean | Remove dynamicCode library |
| -noClean | Do not remove dynamicCode library |
| -name | Name of the equation |
| -fx "pow(x, 3)" | Function "x[0]*x[1]" |
| -dfdx "3*sqr(x)" | First derivative of function "x[1]; x[0]" (entries seperated by ";" for multiple inputs) |
| -d2fdx2 "6*x" | Second derivative of function (only for single inputs) |
| -d3fdx3 "6" | Third derivative of function (only for single inputs) |
| -P "(c b a)" | Polynomial coefficient (a + bx + cx2) |
| -eval "x0" or "(x0 ... xn)" | Evaluate at a list of points |
| -findRoots "(x0 x1 x)" | Find roots between x0 and x1, optionally starting at x |
| -findAllRoots "(x0 x1)" | Find all roots between x0 and x1 |
| -rootSolver | Root solver |
| -findPolyRoots | Find roots of a polynomial (only valid with "P") |
| -minimize "(x0 x1 x)" | Minimize function with bounds x0 and x1, optionally starting at x |
| -minimizer | Method of minimization |
| -integrate "(x0 x1)" | Integate between x0 and x1 |
| -integrator | Integration method |
| -time | Use time (only for cases using meshes) |

> **NOTE:** When using command line options, all function definitions and list entries should be in quotes.

> **NOTE:** When multiple inputs are used, "x0" becomes "(x00 ... x0m)", and applies to all entries that take points/positions.
