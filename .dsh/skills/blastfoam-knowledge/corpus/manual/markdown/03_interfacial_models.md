# Interfacial models

The exchange of momentum and energy is determined by the use of interfacial models. These models are described below and include the equations used to calculate the transfer rates. In general, these models are solved using an explicit Euler integration method. Drag and heat transfer, however, are solved using an analytical solution; the reference used for these solution methods will be provided in the relevant sections.

NOTE: There are more models currently implemented that do not apply to gas-particle flows and, therefore, are not presented at this time. Their descriptions and equations will be added as they become relevant.

## 3.1 Drag models

The drag is responsible for relaxing the velocity difference between two phases to an equilibrium velocity at a rate determined by the drag coefficient, $K_{D,ij}$:

$$
K_{D,ij} = \frac{0.75\alpha_d C_D Re_{ij}\rho_c \nu_c}{d_d^2}
$$
(3.1)

where the Reynolds number between phases $i$ and $j$ is defined as $Re_{ij} = \frac{d_d|u_c - u_d|}{\nu_c}$. The subscripts $c$ and $d$ are used to denote the continuous and dispersed phases, respectively. The term $C_D Re_{ij}$ will be defined by the models discussed in the following sections.

The momentum transfer term is defined as $\dot{M}_{D,ij} = K_{D,ij}(u_j - u_i)$. The solution to the drag relaxation can be found in Appendix B.7 of Houim and Oran (2016). Additionally, an ODE solver can be used to solve the drag relaxation, though this approach is much more computationally expensive.

| Variable | Description |
|---|---|
| swarmCorrelation | Swarm model |

### 3.1.1 SchillerNaumann

The drag model of Schiller and Naumann (1933) calculates the drag coefficient for flow over a single sphere:

$$
C_D Re_{ij} = \begin{cases} 24(1 + 0.15Re_{ij}^{0.687}) & \text{if } Re_{ij} < 1000 \\ 0.44Re_{ij} & \text{else} \end{cases}
$$
(3.2)

| Variable | Description |
|---|---|
| residualRe | Minimum Reynolds number [ ] |

### 3.1.2 WenYu

The Wen and Yu drag model (Enwald et al., 1996) is used for dispersed particulate flow and the drag coefficient is defined as

$$
C_D Re_{ij} = C_D Re_{sSN,ij}\alpha_c^{-2.65}
$$
(3.3)

where $C_D Re_{sSN,ij}$ is the Schiller Naumann drag coefficient multiplied by the Reynolds number, and the Reynolds number used in the drag coefficient is weighted by the dispersed phase volume fraction, i.e.,

$$
Re_{s,ij} = Re_{ij}\alpha_c
$$
(3.4)

| Variable | Description |
|---|---|
| residualRe | Minimum Reynolds number [ ] |

### 3.1.3 Ergun

The Ergun drag model (Enwald et al., 1996) is used for dispersed particulate flow and the drag coefficient is defined as

$$
C_D Re_{ij} = \frac{4}{3}\frac{150(1 - \alpha_c)}{\alpha_c} + 1.75Re_{ij}
$$
(3.5)

### 3.1.4 Gibilaro

The Gibilaro drag model (Enwald et al., 1996) is used for dispersed particulate flow and the drag coefficient is defined as

$$
C_D Re_{ij} = \frac{4}{3}\left(\frac{17.3}{\alpha_2} + 0.336Re_{ij}\right)\alpha_c\alpha_2^{-2.8}
$$
(3.6)

where $\alpha_2 = 1 - \alpha_d$.

### 3.1.5 SyamlalOBrien

The Syamlal O'Brien drag model (Syamlal et al., 1993) is used for dispersed particulate flow and the drag coefficient is defined as

$$
C_D Re_{ij} = \frac{C_{Ds}Re_{ij}\alpha_c}{V_r^2}
$$
(3.7)

where

$$
C_{Ds}Re_{ij} = \left(0.63\sqrt{Re_{ij}} + 4.8\sqrt{V_r}\right)^2
$$
(3.8)

$$
V_r = 0.5\left(A - 0.06Re_{ij} + \sqrt{(0.06Re_{ij})^2 + 0.12Re_{ij}(2B - A) + A^2}\right)
$$
(3.9)

$$
A = \alpha_2^{4.14}
$$
(3.10)

$$
B = \begin{cases} 0.8\alpha_2^{1.28} & \text{if } \alpha_2 < 0.85 \\ \alpha_2^{2.65} & \text{else} \end{cases}
$$
(3.11)

and $\alpha_2 = 1 - \alpha_d$.

### 3.1.6 GidaspowErgunWenYu

The drag model of Gidaspow (1994) is used for dispersed particulate flow and the drag coefficient is a combination of the Wen and Yu drag model (dilute) and Ergun drag model (dense):

$$
C_D Re_{ij} = \begin{cases} C_D Re_{WenYu,ij} & \text{if } \alpha_c > 0.80 \\ C_D Re_{Ergun,ij} & \text{else} \end{cases}
$$
(3.12)

where $C_D Re_{WenYu,ij}$ is the Wen Yu drag coefficient and $C_D Re_{Ergun,ij}$ is the Ergun drag coefficient, both multiplied by the Reynolds number.

| Variable | Description |
|---|---|
| residualRe | Minimum Reynolds number [ ] |

### 3.1.7 GidaspowSchillerNaumann

The Gidaspow-Schiller Naumann drag model (Enwald et al., 1996) is used for dispersed particulate flow and the drag coefficient is defined as

$$
C_D Re_{ij} = C_{Ds}Re_{ij}\alpha_c^{-1.65}
$$
(3.13)

$$
C_{Ds}Re_{ij} = \begin{cases} \frac{24(1 + 0.15Re_{s,ij}^{0.687})}{\alpha_c} & \text{if } Re_{s,ij} < 1000 \\ 0.44Re_{s,ij} & \text{else} \end{cases}
$$
(3.14)

where the Reynolds number used in the drag coefficient is weighted by the dispersed phase volume fraction, i.e.,

$$
Re_{s,ij} = Re_{ij}\alpha_c
$$
(3.15)

| Variable | Description |
|---|---|
| residualRe | Minimum Reynolds number [ ] |

## 3.2 Lift models

The lift interfacial momentum transfer model is used to account for acceleration due to rotation in the continuous phase and is defined as

$$
\dot{M}_{L,ij} = C_{L,ij}\alpha_d\rho_c\left[(u_c - u_i)\times(\nabla\times u_c)\right]
$$
(3.16)

where $C_{L,ij}$ is the lift coefficient between phases $i$ and $j$ and is defined by the model of choice.

### 3.2.1 constant

The lift coefficient is a constant value.

| Variable | Description |
|---|---|
| Cl | Lift coefficient [ ] |

## 3.3 Heat transfer models

The heat transfer model is responsible for relaxing the temperature between two phases at a rate determined by the model of choice. The Prandtl number will be used and is defined as

$$
Pr_{ij} = \frac{\nu_c C_{vc}\rho_c}{\kappa_c}
$$
(3.17)

Again, the subscripts $c$ and $d$ represent the continuous and dispersed phases, respectively. $C_{vc}$ is the continuous phase specific heat at constant volume and $\kappa_c$ is the continuous phase thermal conductivity. The solution to the temperature relaxation can be found in Appendix B.7 of Houim and Oran (2016).

### 3.3.1 RanzMarshall

The Ranz Marshall heat transfer model (Houim and Oran, 2016) defines the heat transfer rate as

$$
\dot{E}_{HT,ij} = \frac{6\alpha_d\kappa_c Nu_{ij}}{d_d^2}
$$
(3.18)

where the Nusselt number is a run-time selectable model, and all other properties are taken from the thermodynamic model.

| Variable | Description |
|---|---|
| NuModel | Nusselt number model |
| residualAlpha | Stabilization value of volume fraction (defaults to that of the phaseModel) |

### 3.3.2 noneNu

This should only be used is a Nusselt number is needed by some other model, but heat transfer is neglected.

## 3.4 Nusselt number models

### 3.4.1 constant

For the constant Nusselt number heat transfer model, Eq. (3.18) is again used, but the Nusselt number is a constant value provided by the user.

| Variable | Description |
|---|---|
| Nu | Nusselt number [ ] |

### 3.4.2 duct

For hollow particles the Nusselt number of Dittus and Boelter (1930) is defined as

$$
Nu_{ij} = 0.023Re_{ij}^{0.8}Pr_{ij}^{0.4}
$$
(3.19)

### 3.4.3 GelperinEinstein

The Nusselt number of Gelperin and Einstein (1971) is defined as

$$
Nu_{ij} = 0.023Re_{ij}^{2/3}Pr_{ij}^{1/3}
$$
(3.20)

### 3.4.4 Gunn

The Nusselt number of Gunn (1978) is defined as

$$
Nu_{ij} = (7 - 10\alpha_c + 5.0\alpha_c^2)(1 + 0.7Re_{ij}^{0.2}Pr_{ij}^{1/3}) + (1.33 - 2.4\alpha_c + 1.2\alpha_c^2)Re_{ij}^{0.7}Pr_{ij}^{1/3}
$$
(3.21)

### 3.4.5 RanzMarschall

The Ranz-Marschall Nusselt number for spheres is defined as

$$
Nu_{ij} = 2 + 0.6Re_{ij}^{1/2}Pr_{ij}^{1/3}
$$
(3.22)

### 3.4.6 sphere

The Nusselt number for spheres is defined as

$$
Nu_{ij} = 2 + 0.4Re_{ij}^{1/2}Pr_{ij}^{1/3}
$$
(3.23)

## 3.5 Mass transfer models

Currently on particle to fluid mass transfer has been implemented. Fluid-fluid mass transfer is not currently supported.

### 3.5.1 none

No mass transfer.

### 3.5.2 reactingParticle

The mass transfer rate is explicitly calculated using the change in mass of a particle where the regression rate is determined by a reaction rate. the reactingParticle diameter model must be used.

## 3.6 Interfacial pressure models

The interfacial pressure model is used to determine the pressure at the interface between two phases.

### 3.6.1 single

The pressure of the given phase is used.

| Variable | Description |
|---|---|
| phase | Name of the phase |

NOTE: For gas-particle flows this option should be used, using the gas phase pressure.

### 3.6.2 volumeAveraged

The volume fraction averaged pressure of the two phases is used.

### 3.6.3 totalPressure

The volume fraction averaged thermodynamic pressure and the mass averaged dynamic pressure is used.

## 3.7 Interfacial velocity models

The interfacial velocity model is used to determine the velocity at the interface between two phases.

### 3.7.1 single

The velocity of the given phase is used.

| Variable | Description |
|---|---|
| phase | Name of the phase |

NOTE: For gas-particle flows this option should be used, using the particle phase velocity.

### 3.7.2 massAveraged

The mass averaged velocity of the two phases is used.
