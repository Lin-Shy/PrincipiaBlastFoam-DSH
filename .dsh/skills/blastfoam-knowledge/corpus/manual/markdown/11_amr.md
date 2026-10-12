# 11 Adaptive Mesh Refinement (AMR)

The dynamic mesh classes have been incorporated from the github repository SOFTX_2018_143 and is based on the work of Rettenmaier et al. (2019). This library introduces 2-D, 2-D axisymmetic, and 3-D (present in OpenFOAM-9) all with the option to include dynamic load balancing. The original work (dynamicRefineBalanceFvMesh and dynamicRefineFvMesh) has been used as the base for the adaptiveFvMesh class. This mesh type has been further developed, specifically for compressible flows, and includes modifications for improved stability with meshes created with snappyHexMesh. Additional polyhedral refinement has been ported from foam-extend's and allows for general polygon refinement.

Because the detonation of explosives may not occur when the simulation starts, the option to begin unrefinement at a designated time ("beginUnrefine") has been added. This allows the mesh to remain refined in specific regions even though the error is initially small.

Additionally, the movingAdaptiveFvMesh class is based on adaptiveFvMesh, and has all of the same features, but includes the ability to use mesh motion. It is recommended to use the velocityLaplacian motion solver.

> **NOTE:** Whilst AMR may be used with meshes created using snappyHexMesh, regions can only be cut at level 0 when using either 2-D or axisymmetric refinement. This is due to the fact that snappyHexMesh uses a 3-D refinement, regardless of the number of solution directions. If refinement is used, the simulation will crash when the mesh is refined in these areas.

> **NOTE:** Meshes that have been "snapped" with snappyHexMesh may work, however crashes may occur. Use at your own risk.

| Entry | Description |
|---|---|
| balance | Is dynamic load balancing used (default is yes) |
| protectedPatches | List of patch names that will not be refined or unrefined (default is none) |
| nRefinementBufferLayers | Number of layers added to refinement (default is 0) |
| nUnrefinementBufferLayers | number oy layers added to unrefinement (default is 0) |
| refine | Use refinement (default is yes) |
| unrefine | Use unrefinement (default is yes) |
| refineInterval | Number of time steps between refinement (default is 1) |
| unrefineInterval | Number of time steps between unrefinement (default is 1) |
| balanceInterval | Number of time steps between balancing (default is 1) |
| beginRefine | Time when refinement can begin (default is 0 s) |
| endRefine | Time when refinement stops (default is great s) |
| beginUnrefine | Time when unrefinement can begin (default is 0 s) |
| endUnrefine | Time when unrefinement stops (default is great s) |
| beginBalance | Time when balancing can begin (default is 0 s) |
| endBalance | Time when balancing stops (default is great s) |
| dumpLevel | Write the cell and point level as viewable fields (false by default) |

## 11.1 Error estimators

In order to determine the cells that can be refined or unrefined, error estimators have been added. Generally, this is achieved by looking for a derivative or difference of a specified fields across all the faces a cell and it neighbours. The maximum value of all face errors of a given cell is taken as the cell center-based value, and is used to define the cells that should be refined. Probe locations are automatically refined up to the maximum level of refinement to remove discontinuities in probe sampling.

| Entry | Description |
|---|---|
| lowerRefineLevel | Error that mesh is refined at |
| unrefineLevel | Error that mesh is unrefined |
| upperRefineLevel | Error that refinement is stopped (default is great) |
| upperUnrefineLevel | Error that unrefinement begins to occur again (default is great) |
| maxRefinement | Maximum number of refinement levels |
| minDx | Minimum cell size |
| refineProbes | Are probes refined (yes by default) |

### 11.1.1 cellSize

Refinement is determined based on the cell size. Either the volume, magnitude of relevant directions (mag), components (cmpt), or the characteristic length (characteristic) can be used. Only the options listed below are used. Because the refinement is based on the cell size the maximumRefinement can be a large number.

| Entry | Description |
|---|---|
| type | size type (volume, mag, cmpt, or characteristic) |
| minVolume | Minimum volume (for volume) |
| maxVolume | Maximum volume (for volume) |
| cmpts | Components (x, y, or z for cmpts) |
| minDX | Minimum size as a vector (for cmpts) |
| maxDX | Maximum size as a vector (for cmpts) |
| minDx | Minimum size (for mag or characteristic) |
| maxDx | Maximum size (for mag or characteristic) |
| maxRefinement | Maximum number of refinement levels (default is 10) |

### 11.1.2 fieldValue

The error is set to the value of the given field

$$
\epsilon_x = x
$$
(11.1)

where $x$ is a field chosen by the user, and can be any scalar field stored within the simulation.

| Entry | Description |
|---|---|
| field | Error field |

### 11.1.3 delta

A basic method to detect sharp changes across faces uses a difference approach, where the error is defined by

$$
\epsilon_{\delta} = |x_{own} - x_{nei}|
$$
(11.2)

where $x$ is a field chosen by the user, and can be any scalar field stored within the simulation. The subscript own denotes values at the current face, while nei denotes the value at the neighboring face.

| Entry | Description |
|---|---|
| field | Field used to compute error |

### 11.1.4 scaledDelta

A basic method to detect sharp changes across faces uses a scaled difference approach, where the error is defined by

$$
\bar{\epsilon}_{\delta} = \frac{|x_{own} - x_{nei}|}{\max(\min(|x_{own} - x_c|,\ |x_{nei} - x_c|),\ x_{min})}
$$
(11.3)

where $x$ is a field chosen by the user, and can be any field stored within the simulation. The minimum value ($x_{min}$) can be specified by the user and is the minimum value that the error will be scaled by.

| Entry | Description |
|---|---|
| field | Field used to compute error |
| minValue (xmin) | Minimum value to scale difference by (default is small) |
| offset (xc) | Offset value to centre error around (default is 0) |

### 11.1.5 Density gradient (densityGradient)

A modified density gradient was defined by Zheng et al. (2008), and uses an error defined by

$$
\epsilon_{\nabla\rho} = \max\left( \frac{|(\nabla\ln\rho)_{C} - (\nabla\ln\rho)_{own}|}{\alpha f \rho_{C}/dl + |(\nabla\ln\rho)_{own}|},\ \frac{|(\nabla\ln\rho)_{C} - (\nabla\ln\rho)_{nei}|}{\alpha f \rho_{C}/dl + |(\nabla\ln\rho)_{nei}|} \right)^{f}
$$
(11.4)

with

$$
(\nabla\ln\rho)_{C} = \frac{\rho_{nei} - \rho_{own}}{|r_{nei} - r_{own}|}
$$
(11.5)

$$
(\nabla\ln\rho)_{nei,own} = \frac{(\nabla\rho)_{nei,own}(r_{nei} - r_{own})}{|r_{nei} - r_{own}|}
$$
(11.6)

$r_{own,nei}$ is the surface normal vector, and $dl = |r_{nei} - r_{own}|$, is the distance between cell centers. This error estimator uses the total density.

### 11.1.6 Lohner

A final error estimation method based on Löhner (1987) is also available. It uses a scaled Laplacian to ensure an error bounded between 0 and 1, and indicates the smoothness of the solution. Due to the fact that the method was initially developed for a Cartesian grid, some modifications were required. Namely, the face value of the tracked field is interpolated using a cubic interpolation method. This allows non-zero smoothness across the faces while still allowing for the method to be used on a non-Cartesian grid.

$$
\epsilon_{\text{Lohner}} = \frac{|x_{own} - 2x_f + x_{nei}|}{|x_{own} - x_f| + |x_{nei} - x_f| + \varepsilon(|x_{own}| + 2|x_f| + |x_{nei}|)}
$$
(11.7)

where $\varepsilon$ is a coefficient which is problem dependent, and $x$ is any scalar field saved within the simulation.

| Entry | Description |
|---|---|
| field | Field name used to compute error |
| epsilon | Scaling coefficient |

### 11.1.7 multiComponent

The multicomponent error estimator allows for multiple errors to be used to define which cells should be refined. Any of the previous methods can be used. A list of names for the error estimators need to be provided, which must correspond to a dictionary with the necessary entries included. The maximum of error at each cell is used for refinement. Each error estimator can use different levels of maximum refinement that are specified in their respective dictionaries.

```
// BlastFoam specific AMR mesh type
dynamicFvMesh
adaptiveFvMesh;
// Error is calculated using the density gradient
errorEstimator
multicomponent;
errorEstimators
(
density
{
errorEstimator densityGradient;
lowerRefineLevel 0.01;
unrefineLevel
0.01;
maxRefinement
2;
}
pressure
{
errorEstimator
scaledDelta;
deltaField
p;
minValue
1e3;
lowerRefineLevel 0.1;
unrefineLevel
0.01;
maxRefinement
2;
}
volumeFraction
{
errorEstimate
fieldValue;
fieldName
alpha.tnt;
//- Only refine when 0.1 < alpha.tnt < 0.6
lowerRefineLevel 0.1;
unrefineLevel
0.05;
upperRefineLevel 0.6;
upperUnrefineLevel 0.7;
maxRefinement
1;
}
);
```

| Entry | Description |
|---|---|
| errorEstimators | List of error estimators to be used |

## 11.2 Dynamic Load Balancing

The ability to use dynamic load balancing is available for 2-D, 2-D axisymmetric, and 3-D meshes. Dynamic load balancing can greatly reduce the computational time required by balancing the cells equally across all processors. However, there are known limitations: due to the way OpenFOAM transfers data between processors, the MPI buffer limit can be exceeded for large cases, leading to the simulation crashing. There are also known problems in the transferring of data for calculated non-scalar fields and movingWall boundary conditions. The fields used within the standard blastFoam solver have addressed this, but if adaptiveFvMesh is used with a different solver, its stability with balancing is not guaranteed.

## 11.3 Example

An example of the optional dynamicMeshDict for use with adaptiveFvMesh class

```
// BlastFoam specific AMR mesh type
dynamicFvMesh
adaptiveFvMesh;
// Error is calculated using the density gradient
errorEstimator
densityGradient;
loadBalance
{
// Is the mesh dynamically balanced
balance yes;
// How many refinement steps between rebalancing
balanceInterval 20;
// Allowable difference between average load
// and max load
allowableImbalance 0.2;
// Decomposition method
method scotch;
}
// How often to refine
refineInterval
1;
// When to begin unrefinement
beginUnrefine 1e-5;
// Refine field in between lower..upper
lowerRefineLevel 1e-2;
// If value < unrefineLevel unrefine
unrefineLevel
1e-2;
// Number of cells between level
nBufferLayers
1;
// Refine cells only up to maxRefinement levels
maxRefinement
4;
// Write the refinement level as a volScalarField
dumpLevel
true;
```
