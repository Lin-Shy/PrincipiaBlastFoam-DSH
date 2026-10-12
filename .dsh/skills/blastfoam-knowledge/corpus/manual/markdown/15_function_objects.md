# 15 Function objects

In addition to the standard OpenFOAM functionObjects, additional blast specific function objects have been added. The standard function objects from the sampling library are automatically included, but additional libraries can also be included. A list of these libraries can be seen in 18. These can be included using the following controlDict entry

```cpp
functions
{
impulse
{
// Additional libraries to include
libs ("libblastFunctionObject.so");
// Function object type
type
impulse;
// writeTime - Writes every output time
// timeStep - Number of time steps
// adjustableRunTime - Specified output interval
writeControl
writeTime;
// Interval between writes
writeInterval 1;
// Reference pressure
pRef 101325;
...
}
}
```

## 15.1 blastProbes

A modified version of the standard OpenFOAM probe utility is also available, where the basic functionality remains the same, with several key additions. First, the ability to append to exiting probe files is now possible, allowing for a single probe file to be used even if a simulation is restarted from a later time. Second, probes that are not found within the mesh can be moved to the nearest face so they can produce valid results. This can be very useful if a probe is needed on a curved face. Lastly, the warning of probes existing on multiple processors has been removed by selecting a single processor on which to probe.

> **NOTE:** When refinement and unrefinement occurs, the probe locations will "jump" to the nearest cell resulting in fluctuations when plotted. This can be eliminated by allowing refinement of probes in dynamicMeshDict ("refineProbes") (this is the default option).

| Entry | Description |
|---|---|
| probeLocations | List of locations to probe |
| fields | Fields to probe at the given points |
| append | Are probes appended to and existing file (default no) |
| fixLocation | Probes follow cell motion (not stationary) |
| adjustLocations | Can probes be moved into the mesh (default no) |
| writeVTK | Probed points are written to a VTK file (default no) |
| interpolationScheme | Method to interpolate probe. Options are cell, cellPoint, cellPointFace, cellPatchConstrained, cellPointWallModified, and pointMVC (default is cell) |

## 15.2 fieldMinMax (fieldMax)

The minimum or maximum value at every cell in a domain is output, allowing for quantities such as maximum impulse and peak pressure to be visualized. This can be done for any field currently stored within the simulation. These fields are automatically saved within the calculation.

| Entry | Description |
|---|---|
| fields | Name of the fields (i.e (rho U p impulse)) |
| restartOnRestart | Reset the min/max on simulation restart (default is no) |
| mode | Type of min/max (component, magnitude, componentMag) |
| minMax | Minimum or maximum (default is max) |

## 15.3 writeTimeList

Additional write times are added using a list of user specified times. This is useful when fields are needed at time that do not correspond to a standard write interval. See validation/blastFoam/woodwardColella for an example.

| Entry | Description |
|---|---|
| times | List of times to write |

## 15.4 conservedQuantities

The volume integrated value of fields can be computed and printed in the output of the solver. The initial, current, total difference, and relative difference is printed. Any fields can be tracked by specifying the names of the fields in the dictionary.

| Entry | Description |
|---|---|
| fields | Fields to track |

> **NOTE:** Currently, the removal and injection of values into a domain is not considered.

## 15.5 vtkTimeSeries surface writer

An extension of the vtk surface writer for writing sampled surfaces can be used so that an additional *.vtk.series file is written in the postProcessing/surfacesName folder with the relative paths to all write times of the given surfaces. This file can then be opened in ParaView to visualize all files in the correct time sequence.

## 15.6 Schlieren (grad)

The gradient of the given field is calculated and written. Only scalar and vector fields can be used.

| Entry | Description |
|---|---|
| field | Fields to take the gradient of |
| result | Name of the result field (Schlieren/grad(field) by default) |

## 15.7 shadowgrap (laplacian)

The Laplacian of the given field is calculated and written

| Entry | Description |
|---|---|
| field | Fields to take the laplacian of |
| result | Name of the result field (shadowgraph/laplacian(field) by default) |

## 15.8 blastMachNo

The blastMachNo replaces the standard machNo available in OpenFOAM by using the speed of sound calculated from the blastFoam specific thermodynamic models.

| Entry | Description |
|---|---|
| phaseName | Name of the phase (default is none) |
| UName | Name of the velocity field (default is U or U.phaseName) |
| result | Name of the Mach number field (default is Ma or Ma.phaseName) |

## 15.9 dynamicPressure

It can be useful in blast simulations to track the dynamic pressure (kinetic energy) of a phase defined as

$$
p_{\mathrm{dyn}} = \frac{1}{2}\rho_i U |U|. \quad (15.1)
$$

The dynamicPressure function object returns the vector of dynamic pressure, where the magnitude of this output is the standard dynamic pressure. Additionally the pressure function object (standard OpenFOAM) can be used to calculate static (if using incompressible) or total pressure and their respective coefficients.

| Entry | Description |
|---|---|
| rhoName | Name of the density field (default is rho) |
| UName | Name of the velocity field (default is U) |

## 15.10 overpressure

This function object calculates and writes the overpressure (e.g. the pressure relative to a given reference pressure, usually ambient) given a pressure field and reference pressure. The field can also be saved to allow for additional sampling.

| Entry | Description |
|---|---|
| pName | Name of the pressure field (default is p) |
| pRef | Reference pressure [Pa] |
| store | Is the field saved (default is no) |

## 15.11 impulse

This function object calculates the impulse in every cell by integrating the overpressure over time using the specified pressure field and reference pressure. The impulse field is automatically saved to allow additional sampling by default.

| Entry | Description |
|---|---|
| pName | Name of the pressure field (default is p) |
| pRef | Reference pressure value [Pa] |

## 15.12 timeOfArrival

This function object tracks the maximum pressure and records the time when the maximum pressure is reached.

| Entry | Description |
|---|---|
| pName | Name of the pressure field (default is p) |
