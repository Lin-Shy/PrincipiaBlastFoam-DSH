# Region models

When multiple regions are used, blastFoam solvers use global poly patches which do not require any special mesh patches to transfer data between field. Instead, the information is transferred using field specific boundary conditions. The interpolation method, sampled patch, and optional displacement field is specified in the constant/regionProperties file. An example of regionProperties can be seen below

```cpp
regions
(
fluid
(air)
solid
(building)
);
interfaces
(
air
{
air_to_building
{
sampleRegion
building;
samplePatch
building_to_air;
mappingType
AMI;
interpolationMethod faceAreaWeight;
}
}
building
{
building_to_air
{
sampleRegion
air;
samplePatch
air_to_building;
displacementField pointD;
}
}
);
```

## Boundary conditions

Several boundary conditions have been implemented that make use of the global patches and are described below.

### globalMapped

Both vol and point field can use the globalMapped boundary condition which directly maps values from one patch to another where the neighbour patch is specified in regionProperties.

| Variable | Description |
|---|---|
| nbrName | Name of field to map from |

### globalInterpolated

Point field can use the globalInterpolated boundary condition which maps a volume field to a point field where the neighbour patch is specified in regionProperties.

| Variable | Description |
|---|---|
| nbrName | Name of field to map from |

### globalTemperatureCoupled

Using the same methodology as the globalMapped boundary condition, the globalTemperatureCoupled boundary condition computes the temperature of a patch using the neighbour temperature, heat transfer coefficient, and radiation heat flux. Optionally when the entire boundary does not overlap the neighbour patch and unmapped temperature can be specified.

| Variable | Description |
|---|---|
| TNbr | Name of neighbour temperature (T by default) |
| hNbr | Name of neighbour convective heat transfer coefficient (none by default) |
| h | Name of convective heat transfer coefficient (none by default) |
| qrNbr | Name of neighbour radiation heat flux (none by default) |
| qr | Name of radiation heat flux (T by default) |
| limitGrad | Is the temperature gradient limited (no by default) |
| unmappedT | Unmapped temperature (293.15 by default) |
