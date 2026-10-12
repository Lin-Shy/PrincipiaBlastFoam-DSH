# Diameter models

The diameter of a dispersed phase is used to calculate surface reaction rates in the Arrhenius activation model as well as interfacial transfer sources in the blastEulerFoam solver. Below are is a short description of the models currently available.

## constant

A constant diameter is used.

> **NOTE:** The diameter field is not written

| Entry | Description |
|---|---|
| d | Diameter of the phase [m] |

## constantMass

The diameter is determined using a reference diameter at a reference density. The mass is defined as

$$
M = \frac{\pi d_0^3 \rho_0}{6}
$$

(9.1)

and the true diameter is calculated using

$$
d = \left( \frac{6M}{\rho\pi} \right)^{1/3}
$$

(9.2)

| Entry | Description |
|---|---|
| rho0 | Reference density [kg/m3] |
| d0 | Reference diameter [m] |

## reacting

The reacting diameter model adds an additional source term in the transport equation for the diameter to increase/decrease the local diameter based on the given reaction rate

$$
\frac{\partial d_i}{\partial t} + u_i \cdot \nabla d_i = k
$$

(9.3)

where k is the specified reaction rate (see Sec. 9.4)

| Entry | Description |
|---|---|
| d | Initial diameter [m] |
| reactionRate | Reaction rate model |

## Reaction Rates

Reaction rates are used to give rates based on temperature and/or pressure currently there are two options, pressure based, and Arrhenius rate

### pressureBased

The pressureBased reaction rate uses a coefficient, pressure scale, pressure offset (in scaled units) and pressure exponent to compute the rate

$$
k = \beta (\bar{p})^\alpha
$$

(9.4)

and $\bar{p} = p \times p_{scale}$. For example, if the pressure relation is in MPa, $p_{scale} = 1e^{-6}$.

| Entry | Description |
|---|---|
| alpha | Pressure exponent [ ] |
| beta | Coefficient [Pa−α] |
| pScale | Pressure scale [ ] |
| offset | Pressure offset [Pa/pScale] |

### Arrhenius

The rate given by the Arrhenius reaction rate is

$$
k = A T^\beta \exp\left(-\frac{T_a}{T}\right)
$$

(9.5)

| Entry | Description |
|---|---|
| A | Rate constant [1/s] |
| beta | Temperature exponent [ ] |
| Ta | Activation temperature [K] |
