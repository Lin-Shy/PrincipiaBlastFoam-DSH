# Burst patches

The ability to have a "bursting" patch can be used with the burst (external patch), burstCyclic (internal with no AMR), or burstCyclicAMI (general internal). All fields require an additional entry in their dictionaries name "intactField" which is used to specify the boundary condition of the field before bursting. The basic burst patch can be created using any mesh generation technique, however the cyclic variations require using the createBaffles utility, standard to OpenFOAM. See Sec. 20.5 for an example of how to create and use the patches.

## 7.1 Burst models

The method to calculate where burst occurs is runtime-selectable and the inputs are placed in the constant/polyMesh/boundary file under the corresponding boundary. This can also be added in either the patch entry within blockMeshDict of snappyHexMeshDict.

| Variable | Description |
|---|---|
| partialBurst | Can individual face burst (no by default) |
| useDelta | Us the difference across coupled patches rather than the maximum value (yes by default) |

### 7.1.1 pressure

Only pressure is used to determine if burst occurs.

| Variable | Description |
|---|---|
| pName | Name of the pressure field (p by default) |
| pRef | Reference pressure (0 by default) |
| pBurst | Pressure at which burst occurs [Pa] |

### 7.1.2 impulse

Only impulse is used to determine if burst occurs. Because an impulse field must be available while running the simulation, it is recommended to use the impulse functionObject (Sec. 15), otherwise some other method of calculating impulse needs to be used.

| Variable | Description |
|---|---|
| impulseName | Name of the impulse field (impulse by default) |
| impulseBurst | Impulse at which burst occurs |

### 7.1.3 pressureAndImpulse

A combination of the pressure and impulse models are used. If either model results in a burst, then burst occurs. Both sets of inputs are required.

### 7.1.4 field

A list of fields and bust values are used to determine if the patch has burst. The inputs can either be given as a single entry ("burstValue"), multiple burst conditions ("burstValues"), or as a list of names and values ("fields" and "values"). The latter is used when writing to remove errors in ParaView. See below for an example.

```cpp
// Model
burstModel
field;
// Single Entry
burstValue
p
4e7;
// Multiple Entries
burstValues
(
p
4e7
impulse 10000
);
// Multiple Entries, split
fields (p
impulse);
values (4e7 10000);
```

| Variable | Description |
|---|---|
| burstValue | Used for single field burst condition [name value] |
| burstValues | Used for multiple field burst condition [(name1 value1 name2 value2 ... nameN valueN)] |
| fields | Name of the fields |
| values | Values at which burst occurs |
