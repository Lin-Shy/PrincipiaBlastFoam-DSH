# Fluid and solid thermodynamic models

Within blastFoam solvers, two different types of basic thermodynamic models
are used. The primary is that of a fluid where internal energy and density, or
temperature and density, are used to find the resulting pressure and speed of
sound. The other, is the solid thermodynamic model, which is only used for
solid phases within multi-fluid solvers and multi-region solvers. These two
models will share the basic thermodynamic classes (eConst, hConst, etc),
as well as the choice in the type (basic, detonating, or multicomponent),
however the solid phase only can use a constant density equation of state,
and the transport model describes the of heat conduction, rather than flow
coefficients (like viscosity). These specific choices will be described below.
To calculate the pressure and temperature given the conservative quantities (mass, momentum, and energy) three components are required: an equation of state, a thermodynamic model, and a transport model. These models are defined in the `phaseProperties` file located in the `constant` directory of each blastFoam case. Each phase within the `phaseProperties` file has several dictionary entries, and these models are specified in the "thermoType" sub-dictionary; the molecular weight must also be defined in the "specie" sub-dictionary.

```cpp
phase_name
{
    type
        basic;
    thermoType
    {
        transport      const;
        thermo         eConst;
        equationOfState idealGas;
    }
    specie
    {
        molWeight      28.97;
    }
    transport
    {
        ...
    }
    thermodynamics
    {
        ...
    }
    equationOfState
    {
        gamma           1.4;
        ...
    }
}
```

> **NOTE:** Not all combinations of thermodynamic model, equation of state, transport, and mixture type are compiled, however using the dynamic compilation available in OpenFOAM, if a valid option is requested it will be compiled at run time and the library will be stored in the `dynamicCode` folder in the case. If any changes are made to the source code (updating/pulling) will not affect these libraries, and the `dynamicCode` folder will need to be removed for re-compilation.

> **NOTE:** By default, any thermodynamic combination that has not previously been compiled will be compiled using the files in `blastfoam/etc/codeTemplates`. These files include support for the standard model, however using the "templateDir" entry a different folder can be used, so that user modified files can be used. This allows for use of user implemented equations of state, thermodynamic, or transport models.

## 5.1 Thermodynamic models

The thermodynamic model is used to calculate the internal energy based solely on the thermal contribution:

$$
e_T = \int C_v(T)\,dT
$$
(5.1)

An additional contribution from the equation of state is given by:

$$
e_{eos}(\rho, T) = \int \left( T\frac{\partial p(\rho, T)}{\partial T} - p(\rho, T) \right) dv
$$
(5.2)

where $v_i = 1/\rho_i$ is the specific volume. The total internal energy is

$$
e = e_T(T) + e_{eos}(\rho, T)
$$
(5.3)

Because the internal energy is the tracked quantity, the temperature is solved using a Newton-Raphson root finding method given the local internal energy and density.

Either internal energy or enthalpy-based coefficients can be used, but only internal energy is used to define the total energy. The conversion from an enthalpy base to an internal energy base is calculated using the specified equation of state. All transport models, with the exception of the tabulated methods were ported from OpenCFD Ltd. (2018b).

$$
C_v = C_p - C_{pMCv}
$$
(5.4)

where $C_{pMCv}$ is determined from the equation of state using

$$
C_{pMCv} = \frac{\partial(p(\rho, e)v)}{\partial T}
$$
(5.5)

For an ideal gas, $C_{pMCv} = \bar{R}/W$ where $\bar{R}$ is the ideal gas constant (8314 [J/mol/K]) and $W$ is the molecular weight in [kg/kmol]. Equations of state that have a pressure with a non-linear dependence on temperature will deviate from this.

When enthalpy is used, the internal energy is calculated using

$$
e = h - \frac{p}{\rho}
$$
(5.6)

> **NOTE:** By default the internal energy is limited so that the temperature is greater than 0. If "limitT" is set to "no" the temperature and energy will not be limited. Caution should be used with this option.

### 5.1.1 eConst

Internal energy is calculated using a constant value of specific heat at constant volume.

$$
e_T(T) = C_v(T - T_{ref}) + E_{s,ref}
$$
(5.7)

| Variable | Description |
|---|---|
| $C_v$ | Specific at constant volume [J/kg/K] |
| $T_{ref}$ | Reference temperature [K] (293.15 K default) |
| $E_{sref}$ | Reference sensible internal energy [J/kg/] ($T_{ref} C_v$ default) |
| $H_f$ | Heat of formation [J/kg] |

### 5.1.2 ePolynomial

Internal energy is calculated using polynomial with powers of T.

$$
e_T(T) = \sum_{i=0}^{7} C_{v,i}T^i
$$
(5.8)

| Variable | Description |
|---|---|
| $C_v$Coeffs<8> | Specific heat at constant volume polynomial coefficients |
| $H_f$ | Heat of formation [J/kg] |
| $S_f$ | Standard entropy [J/kg/K] |

### 5.1.3 ePower

Internal energy using a power function of temperature.

$$
e_T(T) = C_v(T)T
$$
(5.9)

$$
C_v(T) = C_0 \left( \frac{T}{T_{ref}} \right)^{n_0}
$$
(5.10)

| Variable | Description |
|---|---|
| $C_0$ | Reference heat capacity at constant volume [J/kg/K] |
| $n_0$ | Exponent of the power function |
| $T_{ref}$ | Reference temperature [K] |
| $H_f$ | Heat of formation [J/kg] |

### 5.1.4 eIcoTabulated

The incompressible tabulated thermodynamic model can be used to calculate the temperature using temperature to lookup the internal energy. The data is read from a one dimensional table. The specific heat are calculated using finite difference derivatives to the tables. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x" and "f" names are "T" and "e" respectively. A heat of formation, "Hf", must also be provided.

### 5.1.5 eTabulated

The tabulated thermodynamic model can be used to calculate the temperature using density and temperature to find internal energy. The data is read from a two dimensional table. The specific heat are calculated using finite difference derivatives to the tables. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x", "y", and "f" names are "rho", "T", and "e" respectively. A heat of formation, "Hf", must also be provided.

> **NOTE:** The equation of state contribution of internal energy is not included so this must be included in the tables provided.

### 5.1.6 hConst

Enthalpy is calculated using a constant value of specific heat at constant pressure.

$$
h_T(T) = C_p(T - T_{ref}) + H_{s,ref}
$$
(5.11)

| Variable | Description |
|---|---|
| $C_p$ | Specific at constant pressure [J/kg/K] |
| $T_{ref}$ | Reference temperature [K] (293.15 K default) |
| $H_{sref}$ | Reference sensible enthalpy [J/kg/] ($T_{ref} C_p$ default) |
| $H_f$ | Heat of formation [J/kg] |

### 5.1.7 hPolynomial

Enthalpy is calculated using polynomial with powers of T.

$$
h_T(T) = \sum_{i=0}^{7} C_{p,i}T^i
$$
(5.12)

| Variable | Description |
|---|---|
| $C_p$Coeffs<8> | Specific heat at constant pressure polynomial coefficients |
| $H_f$ | Heat of formation [J/kg] |
| $S_f$ | Standard entropy [J/kg/K] |

### 5.1.8 hPower

Internal energy using a power function of temperature.

$$
h_T(T) = C_p(T)T
$$
(5.13)

$$
C_v(T) = C_0 \left( \frac{T}{T_{ref}} \right)^{n_0}
$$
(5.14)

| Variable | Description |
|---|---|
| $C_0$ | Reference heat capacity at constant volume [J/kg/K] |
| $n_0$ | Exponent of the power function |
| $T_{ref}$ | Reference temperature [K] |
| $H_f$ | Heat of formation [J/kg] |

### 5.1.9 hIcoTabulated

The incompressible tabulated thermodynamic model can be used to calculate the temperature using temperature to lookup the enthalpy. The data is read from a one dimensional table. The specific heat are calculated using finite difference derivatives to the tables. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x" and "f" names are "T" and "h" respectively. A heat of formation, "Hf", must also be provided.

### 5.1.10 hTabulated

The tabulated thermodynamic model can be used to calculate the temperature using density and temperature to find enthalpy. The data is read from a two dimensional table. The specific heat are calculated using finite difference derivatives to the tables. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x", "y", and "f" names are "rho", "T", and "h" respectively. A heat of formation, "Hf", must also be provided.

> **NOTE:** The equation of state contribution of internal energy is not included so this must be included in the tables provided.

### 5.1.11 JANAF

The JANAF thermodynamic model can be used in which the enthalpy is represented by a temperature based polynomial (OpenCFD Ltd., 2018b). Seven coefficients must be specified for both the low temperature and high temperature states, as well as the high, low, and switching temperatures. Currently, this model is only available for ideal gases.

| Variable | Description |
|---|---|
| `highCpCoeffs` | High enthalpy coefficients |
| `lowCpCoeffs` | Low enthalpy coefficients |
| $T_{low}$ | Minimum temperature [K] |
| $T_{common}$ | Switching temperature [K] |
| $T_{high}$ | Maximum temperature [K] |

## 5.2 Equation of states

In order to more easily handle a variety of equations of state, both temperature-based equations of state and internal energy based equations of state (e.g. in Mie-Grüneisen form) can be used.

### 5.2.1 rhoConst

For a solid phase, it is assumed to have a constant density, $\rho_0$, and maintains a reference pressure $p_{ref}$. Because a solid thermodynamic model is never used to transport mass, the reference pressure is arbitrary and therefore set to 0 [Pa] by default.

| Variable | Description |
|---|---|
| $\rho_0$ | reference density [ kg/m³ ] |
| $p_{ref}$ | Reference pressure [Pa ] (default 101235 Pa) |

### 5.2.2 Internal energy based (Mie-Grüneisen form)

The Mie-Grüneisen form uses two contributions to calculate the pressure, and ideal gas term contribution, and a deviation term.

$$
p = (\Gamma_i - 1)\rho_i e - \Pi_i
$$
(5.15)

$\Gamma_i$, also called the Grüneisen coefficient, and $\Pi_i$ is the pressure deviation from an ideal gas and is specific to the equation of state. Using these quantities, the speed of sound is written as

$$
c^2_i = \frac{\Gamma_i p + \Pi_i}{\rho_i} - \delta_i(\Gamma_i - 1)
$$
(5.16)

where $\delta_i$ is defined

$$
\delta_i = \frac{-[p + \Pi_i]\Gamma'_i}{[\Gamma_i - 1]^2} + \frac{\Pi'_i}{\Gamma_i - 1}
$$
(5.17)

and where $\Gamma'_i$ and $\Pi'_i$ are the derivatives with respect to the phase density.

#### 5.2.2.1 idealGas

For an ideal gas, the pressure is defined as

$$
p_i = (\gamma_i - 1)\rho_i e_i
$$
(5.18)

The functions as defined to represent an ideal gas in Mie-Grüneisen form are:

$$
\Gamma_i = \gamma_i
$$
(5.19)

$$
\Pi_i = 0
$$
(5.20)

$$
\delta_i = 0
$$
(5.21)

| Variable | Description |
|---|---|
| `gamma` | Specific heat ratio [ ] |

#### 5.2.2.2 stiffenedGas

For a material obeying the stiffened EOS, the pressure is defined as

$$
p_i = (\gamma_i - 1)\rho_i e_i - \gamma_i a_i
$$
(5.22)

where $a_i$ and $\gamma_i$ are material properties (Zheng et al., 2011). In the Mie-Grüneisen form

$$
\Gamma_i = \gamma_i
$$
(5.23)

$$
\Pi_i = \gamma_i a_i
$$
(5.24)

and

$$
\delta_i = 0
$$
(5.25)

| Variable | Description |
|---|---|
| `a` | Reference pressure [Pa] |
| `gamma` | Specific heat ratio [ ] |

#### 5.2.2.3 linearTillotson

The linear Tillotson equation of state was presented by (Wardlaw et al., 1998), and the pressure is defined as

$$
p_i = p_{0,i} + \omega_i\rho_i(e_T - e_{0,i}) + A_i\mu + B_i\mu^2 + C_i\mu^3
$$
(5.26)

where $A_i$, $B_i$, $C_i$, and $\omega_i$ are material coefficients, and $p_{0,i}$ and $e_{0,i}$ are the reference pressure and internal energy. $\mu$ is defined as $\rho_i/\rho_{0,i} - 1$. The cavitation pressure, $p_{cav}$ is used as the minimum pressure which occurs when the density is sufficiently below the reference density.

In the Mie-Grüneisen form

$$
\Gamma_i = \omega_i + 1
$$
(5.27)

and

$$
\Pi_i = \omega_i\rho_i e_{0,i} - p_{0,i} - A_i\mu - B_i\mu^2 - C_i\mu^3
$$
(5.28)

and

$$
\delta_i = \frac{e_{0,i} - A + 2B\mu + 3.0C\mu^2}{\rho_{0,i}\omega_i}
$$
(5.29)

| Variable | Description |
|---|---|
| $p_0$ | Reference pressure [Pa] |
| `rho0` | Reference density [kg/m³] |
| $e_0$ | Reference internal energy [kJ/kg] |
| `omega` | Model coefficient [ ] |
| $A$ | Model coefficient [Pa] |
| $B$ | Model coefficient [Pa] |
| $C$ | Model coefficient [Pa] |
| `pCav` | Cavitation pressure [Pa] |

#### 5.2.2.4 Tillotson

The Tillotson equation of state was originally developed for metals by Tillotson (1962), and the pressure is defined as

$$
p_i = \max\left( \rho_i e\left( a + \frac{b}{\frac{e}{e_{0,i}\eta^2} + 1} \right) + A_i\mu + B_i\mu^2, p_{cav} \right)
$$
(5.30)

where $A_i$, $B_i$, $C_i$, and $\omega_i$ are material coefficients, and $p_{0,i}$ and $e_{0,i}$ are the reference pressure and internal energy (Wardlaw et al., 1998). $\mu$ is defined as $\rho_i/\rho_{0,i} - 1$. The cavitation pressure, $p_{cav}$ is used as the minimum pressure which occurs when the density is sufficiently below the reference density.

In the Mie-Grüneisen form

$$
\Gamma_i = a_i x + \frac{b_i e_{0,i}\rho_i^2}{x} - \frac{b_e e_{0,i}(\rho_i\rho_{0,i})^2}{x^2} + 1
$$
(5.31)

where

$$
x_i = e\rho^2_{0,i} + e_{0,i}\rho^2_i
$$
(5.32)

and

$$
\Pi_i = -A_i\mu - B_i\mu^2 - b_i\frac{(e\rho_i\rho_{0,i})^2 e_{0,i}\rho_i}{(e\rho^2_{0,i} + e_{0,i}\rho^2_i)^2}
$$
(5.33)

and $\delta_i$ is calculated using (5.17)

| Variable | Description |
|---|---|
| `rho0` | Reference density [kg/m³] |
| $e_0$ | Reference internal energy [kJ/kg] |
| `a` | Model coefficient [ ] |
| `b` | Model coefficient [ ] |
| $A$ | Model coefficient [Pa] |
| $B$ | Model coefficient [Pa] |
| `pCav` | Cavitation pressure [Pa] |

#### 5.2.2.5 Tait

For a material obeying the stiffened EOS, the pressure is defined as

$$
p_i = (\gamma_i - 1)\rho_i e_i - \gamma_i(b_i - a_i)
$$
(5.34)

where $a_i$, $b_i$, and $\gamma_i$ are material properties (Zheng et al., 2011). In the Mie-Grüneisen form

$$
\Gamma_i = \gamma_i
$$
(5.35)

$$
\Pi_i = \gamma_i(b_i - a_i)
$$
(5.36)

and

$$
\delta_i = 0
$$
(5.37)

| Variable | Description |
|---|---|
| `a` | Material parameter [Pa] |
| `b` | Material parameter [Pa] |
| `gamma` | Specific heat ratio [ ] |

#### 5.2.2.6 vanderWaals

For a gas described by the generalized van der Waals equation of state (Zheng et al., 2011), the pressure is defined as

$$
p_i = \frac{\gamma_i - 1}{1 - b_i\rho_i}(\rho_i e_i + a_i\rho^2_i) - (a_i\rho^2_i + c_i)
$$
(5.38)

Putting the pressure in the Mie-Grüneisen form, we obtain

$$
\Gamma_i = \frac{\gamma_i - 1}{1 - b_i\rho_i} + 1
$$
(5.39)

$$
\Pi_i = \left( 1 - \frac{\gamma_i - 1}{1 - b_i\rho_i} \right)a_i\rho^2_i + \left( \frac{\gamma_i - 1}{1 - b_i\rho_i} + 1 \right)c_i
$$
(5.40)

and

$$
\delta_i = -b_i\frac{p_i + a_i\rho^2_i}{\gamma_i - 1} + \left( \frac{1 - b_i\rho_i}{\gamma - 1} - 1 \right)2a_i\rho_i
$$
(5.41)

| Variable | Description |
|---|---|
| `a` | Attraction between particles [kg⁻¹ m⁵ s⁻²] |
| `b` | Specific volume excluded due to particle volume [kg⁻¹ m³] |
| `c` | Reference pressure [Pa] |
| `gamma` | Specific heat ratio [ ] |

#### 5.2.2.7 LSZK

The Landau, Stanyukovich, Zeldovich, and Kompaneets equation of state is a simple model for describing an ideal explosive (Lutzky, 1964; Needham, 2018). It takes a form similar to a stiffened gas or Tait EOS, with

$$
\Gamma_i = \gamma_i
$$
(5.42)

$$
\Pi_i = a_i\rho^{b_i}_i
$$
(5.43)

and

$$
\delta_i = 0
$$
(5.44)

| Variable | Description |
|---|---|
| `a` | Model constant [kg¹⁻ᵇ s⁻² m³ᵇ⁻¹] |
| `b` | Pressure exponent [ ] |
| `gamma` | Specific heat ratio [ ] |

#### 5.2.2.8 JWL

The more complicated Jones Wilkins Lee EOS is often used to define energetic materials (Zheng et al., 2011), and has a pressure deviation given by

$$
\Pi_i = A_ie^{-R_{1,i}V}\left( \frac{\omega_i}{R_{1,i}V} - 1 \right) + B_ie^{-R_{2,i}V}\left( \frac{\omega_i}{R_{2,i}V} - 1 \right) - \rho_i\omega_ie_{0,i}
$$
(5.45)

where $V = \rho_{0,i}/\rho_i$.

$$
\Gamma_{r,i} = \omega_i + 1
$$
(5.46)

and

$$
\delta_{r,i} = A_ie^{-\frac{R_{1,i}\rho_{0,i}}{\rho_i}}\left[ \omega_i\left( \frac{1}{R_{1,i}\rho_{0,i}} + \frac{1}{\rho_i} \right) - \frac{R_{1,i}\rho_{0,i}}{\rho_i^2} \right]\frac{1}{\omega_i} + B_ie^{-\frac{R_{2,i}\rho_{0,i}}{\rho_i}}\left[ \omega_i\left( \frac{1}{R_{2,i}\rho_{0,i}} + \frac{1}{\rho_i} \right) - \frac{R_{2,i}\rho_{0,i}}{\rho_i^2} \right]\frac{1}{\omega_i} - e_{0,i}
$$
(5.47)

> **NOTE:** The JWL model can also be used to describe the unreacted state if a detonating model is used with the `solidJWL` type. For the solid case, $e_{0,i}$ is calculated so that there is zero pressure at the reference density, and uses an offset pressure, "pRef". Thermal energy is also not considered for the solid case

| Variable | Description |
|---|---|
| $A$ | Model coefficient [Pa] |
| $B$ | Model coefficient [Pa] |
| $R_1$ | Model coefficient [ ] |
| $R_2$ | Model coefficient [ ] |
| `rho0` | Unreacted or reference density [kg m⁻³] |
| `omega` | Grüneisen coefficient [ ] |
| $e_0$ | Offset energy (0 by default for gas) [J/Kg] |
| `pRef` | Offset pressure (only for solid, 0 by default) [Pa] |

#### 5.2.2.9 CochranChan

The Cochran Chan EOS can be used to describe a solid material (Zheng et al., 2011), and has a reference pressure given by

$$
p_{ref,i} = A_iV_i^{1-E_{1,i}} - B_iV_i^{1-E_{2,i}}
$$
(5.48)

The functions used to defined the Mie-Grüneisen equations are

$$
\Gamma_i = \Gamma_{0,i} + 1,
$$
(5.49)

$$
\Pi_i = \Gamma_{0,i}\rho_i\left( -\frac{A_i}{(E_{1,i} - 1)\rho_{0,i}}V_i^{1-E_{1,i}} + \frac{B_i}{(E_{2,i} - 1)\rho_{0,i}}V_i^{1-E_{2,i}} - e_{0,i} \right) - p_{ref,i}
$$
(5.50)

and

$$
\delta_i = \frac{A_i}{E_{1,i}}\left[ \frac{E_{1,i}V_i^{-E_{1,i}}}{E_{1,i} - \Gamma_{0,i} - 1}\frac{1}{\rho_i} + \frac{\Gamma_{0,i}}{\rho_{0,i}} \right]\frac{1}{\Gamma_{0,i}} + \frac{B_i}{E_{2,i}}\left[ \frac{E_{2,i}V_i^{-E_{2,i}}}{E_{2,i} - \Gamma_{0,i} - 1}\frac{1}{\rho_i} + \frac{\Gamma_{0,i}}{\rho_{0,i}} \right]\frac{1}{\Gamma_{0,i}} - e_{0,i}
$$
(5.51)

| Variable | Description |
|---|---|
| $A$ | Model coefficient [Pa] |
| $B$ | Model coefficient [Pa] |
| $E_1$ | Model coefficient [ ] |
| $E_2$ | Model coefficient [ ] |
| `rho0` | Reference density [kg/m³] |
| `Gamma0` | Grüneisen coefficient [ ] |
| $e_0$ | Reference energy (0 by default) [J/Kg ] |

#### 5.2.2.10 DoanNickel

The Doan-Nickel EOS includes changes in the composition of air at high temperatures and the changing specific heat ratio due to dissociation of molecules Doan and Nickel (1963). Due to the way this model is defined, it can currently only be used with inviscid fluids and a constant specific heat at constant volume (eConst). The specific heat is a function of the density and internal energy and is defined as

$$
\Gamma_i = 1 + \left( 0.161 + 0.255e^{\tilde{e}/e_1}f_1 + 0.280e^{\tilde{e}/e_2}(1 - f_1) + 0.137e^{\tilde{e}/e_3}f_2 + 0.050f_3 \right) \left( \frac{\rho_i}{\rho_{0,i}} \right)^{\alpha(\rho_i,\tilde{e})}
$$
(5.52)

where $\tilde{e} = e \cdot 10^{-6}$. $e_1 = 4.46$, $e_2 = 6.63$, and $e_3 = 25.5$ are the internal energies at which oxygen dissociates, everything is dissociated, and electrons contribute, respectively. $\rho_{0,i}$ is the density of air at sea-level (1.293 [kg/m³], and

$$
\alpha(\rho_i, \tilde{e}) = [0.048f_1 + 0.032(1 - f_1)(1 - f_2)]\log_{10}(\tilde{e}) + 0.045f_3
$$
(5.53)

with

$$
f_1 = \frac{1}{\exp\left( \frac{\tilde{e} - e_{O_2\to 2O}}{\Delta e_{O_2\to 2O}} \right) + 1}
$$
(5.54)

$$
e_{O_2\to 2O} = 8.5 + 0.357\log_{10}\left( \frac{\rho_i}{\rho_{0,i}} \right)
$$
(5.55)

$$
\Delta e_{O_2\to 2O} = 0.975\left( \frac{\rho_i}{\rho_{0,i}} \right)^{0.05}
$$
(5.56)

$$
f_2 = \frac{1}{\exp\left( \frac{e_{N_2\to 2N} - \tilde{e}}{\Delta e_{N_2\to 2N}} \right) + 1}
$$
(5.57)

$$
e_{N_2\to 2N} = 45.0\left( \frac{\rho_i}{\rho_{0,i}} \right)^{0.0157}
$$
(5.58)

$$
\Delta e_{N_2\to 2N} = 4.0\left( \frac{\rho_i}{\rho_{0,i}} \right)^{0.085}
$$
(5.59)

$$
f_3 = \frac{1}{\exp\left( \frac{e_e - \tilde{e}}{\Delta e_e} \right) + 1}
$$
(5.60)

$$
e_e = 160.0
$$
(5.61)

and

$$
\Delta e_e = 6.0
$$
(5.62)

Due to the complexity of the model, and the fact that it was specifically developed as a model for air, all coefficients are hard-coded and cannot be changed. This equation of state should only be used to represent standard air.

### 5.2.3 Temperature-based

While it is preferable to use an internal energy based equation of state for compressible flows, some equations of state cannot be converted, and therefore use the local temperature to define the thermodynamic pressure. Generally the Grüneisen coefficient used to calculate the shared pressure is defined as

$$
\Gamma_i = \frac{v_i}{C_v}\frac{\partial p}{\partial T}
$$
(5.63)

where $C_v$ is the specific heat at constant volume, and the speed of sound is defined

$$
c^2_i = v^2_i\left[ \left( \frac{\partial p_i}{\partial T} \right)^2 \frac{T}{C_v} - \frac{\partial p}{\partial v_i} \right]
$$
(5.64)

Unless otherwise specified, these relations are used to calculate the relevant quantities.

#### 5.2.3.1 perfectGas

The perfect gas equation of state uses the standard ideal gas pressure relation, however the specific heat ratio is not held constant, allowing for the use of non-constant heat capacity models.

$$
p_i = RT\rho_i
$$
(5.65)

#### 5.2.3.2 JWLC

The C-form of the Jones Wilkins Lee equation of state (Souers et al., 2000) does not have a dependence on the temperature or internal energy and has a pressure defined as

$$
p_i = A_ie^{-R_{1,i}V} + B_ie^{-R_{2,i}V} + \frac{C_i}{V^{1+\omega_i}}
$$
(5.66)

the speed of sound if defined

$$
c^2_i = \frac{V^2}{\rho_{0,i}}\left( A_ie^{-R_{1,i}V} + B_ie^{-R_{2,i}V} + \frac{C_i(1 + \omega_i)}{V^{2+\omega_i}} \right)
$$
(5.67)

The Grüneisen coefficient is the same as the standard JWL equation of state.

| Variable | Description |
|---|---|
| $A$ | Model coefficient [Pa] |
| $B$ | Model coefficient [Pa] |
| $C$ | Model coefficient [Pa] |
| $R_1$ | Model coefficient [ ] |
| $R_2$ | Model coefficient [ ] |
| `rho0` | Unreacted or reference density [kg m⁻³] |
| `omega` | Grüneisen coefficient [ ] |

#### 5.2.3.3 AbelNobel

The equation of state of Abel-Nobel is commonly used for modeling simulate explosive materials, specifically for propellants (Johnston, 2005). Unlike the JWL equation of state, the BKW models uses the temperature, rather than the internal energy, to define the pressure.

$$
p_i = \frac{RT\rho_i}{1 - b_i\rho_i}
$$
(5.68)

where $b$ is the co-volume of the fluid.

| Variable | Description |
|---|---|
| `b` | Co-volume [m³/kg ] |

#### 5.2.3.4 BKW

The Becker-Kistiakowsky-Wilson equation of state is another equation of state that is commonly used to simulate explosive materials (Mader, 1963). Unlike the JWL equation of state, the BKW models uses the temperature, rather than the internal energy, to define the pressure.

$$
p_i = RT\rho_i\left( 1 + xe^{\beta x} \right)
$$
(5.69)

where

$$
x = \frac{\kappa k\rho_i}{W_i(T + \theta)^a}
$$
(5.70)

and $W_i$ is the molecular weight in [kg/kmol].

| Variable | Description |
|---|---|
| `beta` | Model coefficient [ ] |
| `a` | Temperature exponent [ ] |
| `Theta` | Model coefficient [K] |
| `kappa` | Model coefficient [Kᵃ] |
| `k` | Specie co-volume [m³/kmol] |

#### 5.2.3.5 BWR

The Benedict-Webb-Rubin equation of state was developed by (Benedict et al., 1942) to describe real gases using a set of eight coefficients that must be experimentally determined. The pressure is defined as

$$
p_i = RT\rho_i + \left( B_0RT - A_0 - \frac{C_0}{T^2} \right)\rho^2_i + (bRT - a)\rho^3_i + a\alpha\rho^6_i + \frac{c\rho^3_i}{T^2(1 + \gamma\rho^2_i)}e^{-\gamma\rho^2_i}
$$
(5.71)

| Variable | Description |
|---|---|
| $A_0$ | Model coefficient |
| $B_0$ | Temperature exponent |
| $C_0$ | Model coefficient |
| `a` | Model coefficient |
| `b` | Model coefficient |
| `c` | Model coefficient |
| `alpha` | Model coefficient |
| `gamma` | Specific heat ratio [ ] |

#### 5.2.3.6 Murnaghan

The Murnaghan (or Munahan) equation of state is used for solid material and has no temperature dependence (Souers et al., 2000). The pressure is a function of only the density and is defined as

$$
p_i = p_{ref} + \frac{1}{\kappa n}\left( \frac{\rho_i}{\rho_{0,i}} - 1 \right)^n
$$
(5.72)

| Variable | Description |
|---|---|
| `pRef` | Reference pressure [Pa] |
| `rho0` | Reference density [kg/m³] |
| `kappa` | Model coefficient (1/K0) [Pa⁻¹] |
| $K_0$ | Bulk modulus (can be used in place of $\kappa$) [Pa] |
| `n` (or $K_0$) | Model coefficient (default 1) [ ] |
| `Gamma` | Grüneisen coefficient [ ] |

### 5.2.4 tabulatedEOS

The tabulated equation of state can be used to calculate the pressure using the density and temperature. The data is read from a two dimensional tables. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x", "y", and "f" names are "rho", "T", and "p" respectively.

#### 5.2.4.1 BirchMurnaghan2

The second order Birch-Murnaghan equation of state is the second order expansion of the Birch-Murnaghan model. The pressure is defined as

$$
p_i = p_{ref} + \frac{3K_0}{2K'_0}\left[ \left( \frac{\rho_i}{\rho_{0,i}} \right)^{7/3} - \left( \frac{\rho_i}{\rho_{0,i}} \right)^{5/3} \right]
$$
(5.73)

Many coefficients can be found for this in Zheng and Zhao (2016).

| Variable | Description |
|---|---|
| `pRef` | Reference pressure [Pa] |
| `rho0` | Reference density [kg/m³] |
| $K_0$ | Bulk modulus [Pa] |
| `Gamma` | Grüneisen coefficient [ ] |

#### 5.2.4.2 BirchMurnaghan3

The Third order Birch-Murnaghan equation of state is the third order expansion of the Birch-Murnaghan (see Zheng and Zhao (2016)). The pressure is defined as

$$
p_i = p_{ref} + \frac{3K_0}{2K'_0}\left[ \left( \frac{\rho_i}{\rho_{0,i}} \right)^{7/3} - \left( \frac{\rho_i}{\rho_{0,i}} \right)^{5/3} \right] \times \left( 1 + 0.75(K'_0 - 4)\left[ \left( \frac{\rho_i}{\rho_{0,i}} \right)^{2/3} - 1 \right] \right)
$$
(5.74)

| Variable | Description |
|---|---|
| `pRef` | Reference pressure [Pa] |
| `rho0` | Reference density [kg/m³] |
| $K_0$ | Bulk modulus [Pa] |
| `K0Prime` | Change in bulk modulus w.r.t. pressure [ ] |
| `Gamma` | Grüneisen coefficient [ ] |

### 5.2.5 eTabulated/tabulatedMG

In addition to the previously mentioned equations of state and thermodynamic models, tabulated models may also be used. This is useful when simulating real gasses, and high temperatures and pressures when standard models are no longer sufficient. Any combination of pressure and temperature tables can be used, as long as they are a function of density and internal energy (x and y, respectively). The internal energy is initialized using a reverse look up given a pressure and a density. See 12.1 for more information on usage.

> **NOTE:** Because of the way the selection of models is handled, this option will not show up as an available option if other models are used. Currently only const, icoTabulated, and tabulated transport models are available.

An example is shown below:

```cpp
phase
{
    type basic;
    thermoType
    {
        transport      const;
        thermo         eTabulated;
        equationOfState tabulatedMG;
    }
    specie
    {
        molWeight      28.97;
    }
    tranpsport
    {
        mu      0;
        Pr      0;
    }
    thermodynamics
    {
        file     "T.csv";
        mod      ln;
        // log(p_i)=p_table
        rhoMod   log10;
        // log_10(rho_i)=minRho+i*deltaRho
        nRho     7;
        // Number of columns
        minRho   -3.0;
        // 0.001 kg/m^3
        deltaRho 1.0;
        eMod     ln;
        // log(e)=mine+j*deltaE
        nE       40;
        // Number of rows
        minE     11.8748;
        deltaE   1.0;
    }
    equationOfState
    {
        file     "p.csv";
        mod      ln;
        // log(p_i)=p_table
        rhoMod   log10;
        // log_10(rho_i)=minRho+i*deltaRho
        nRho     7;
        // Number of columns
        minRho   -3.0;
        // 0.001 kg/m^3
        deltaRho 1.0;
        rhoIsReal false;
        eMod     ln;
        // log(e)=mine+j*deltaE
        nE       40;
        // Number of rows
        minE     11.8748;
        deltaE   1.0;
        eIsReal false;
    }
}
```

## 5.3 Fluid Transport

The transport models are used to define quantities such as viscosity and thermal diffusion. Only Newtonian viscosity models are currently available. All transport models, with the exception of the tabulated methods ported from OpenCFD Ltd. (2018b).

### 5.3.1 const

Constant values for viscosity ($\mu$) and Prandtl number are used.

$$
\kappa = \mu C_p/Pr
$$
(5.75)

| Variable | Description |
|---|---|
| `mu` | Dynamic viscosity [Kg/m/s] |
| `Pr` | Prandtl number [ ] |

### 5.3.2 sutherland

Viscosity is calculated using Sutherland's formula for viscosity

$$
\mu(T) = \frac{A_s\sqrt{T}}{1 + T_s/T}
$$
(5.76)

$$
\kappa = \mu C_v\left( 1.32 + \frac{1.77R}{C_v} \right)
$$
(5.77)

| Variable | Description |
|---|---|
| $T_s$ | Sutherland temperature [K] |
| $A_s$ | Sutherland coefficient [kg/m/s/K^1/2] |

### 5.3.3 logPolynomial

Transport package using polynomial functions of the natural logarithm of temperature for the natural logarithm of dynamic viscosity and thermal conductivity:

$$
\log(\mu(T)) = \sum_{i=0}^{7} \mu_i(\log(T))^i
$$
(5.78)

$$
\log(\kappa(T)) = \sum_{i=0}^{7} \kappa_i(\log(T))^i
$$
(5.79)

| Variable | Description |
|---|---|
| `muCoeffs<8>` | Dynamic viscosity coefficients |
| `kappaCoeffs<8>` | Conductivity coefficients |

### 5.3.4 polynomial

Transport package using polynomial functions of temperature for the dynamic viscosity and thermal conductivity:

$$
\mu(T) = \sum_{i=0}^{7} \mu_iT^i
$$
(5.80)

$$
\kappa(T) = \sum_{i=0}^{7} \kappa_iT^i
$$
(5.81)

| Variable | Description |
|---|---|
| `muCoeffs<8>` | Dynamic viscosity coefficients |
| `kappaCoeffs<8>` | Conductivity coefficients |

### 5.3.5 WLF

Transport package using the Williams-Landel-Ferry model for viscosity of polymer melts (Williams et al., 1955):

$$
\mu(T) = \mu_0\exp\left( \frac{-C_1(T - T_r)}{C_2 + T - T_r} \right)
$$
(5.82)

$$
\kappa(T) = \frac{C_p(T)\mu(T)}{Pr}
$$
(5.83)

| Variable | Description |
|---|---|
| $\mu_0$ | Reference dynamic viscosity [Pa s] |
| `TRef` | Referece temperature [K] |
| $C_1$ | WLF constant [ ] |
| $C_2$ | WLF constant [K] |
| `Pr` | Prandtl number [ ] |

### 5.3.6 icoTabulated

The tabulated, incompressible transport model can be used to calculate the viscosity and conductivity using only the temperature. The data is read from two one dimensional tables. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x" and "f" names are "T" and "mu"/"kappa" respectively.

### 5.3.7 tabulated

The tabulated transport model can be used to calculate the viscosity and conductivity using the density and temperature. The data is read from two, two dimensional tables. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x", "y", and "f" names are "rho", "T", and "mu"/"kappa" respectively.

## 5.4 Solid Transport

The transport models are used to define the thermal conductivity of the material. All transport models, with the exception of the tabulated methods are ported from OpenCFD Ltd. (2018b).

### 5.4.1 constIso

A constant, scalar value (isotropic), is used for for thermal conductivity.

| Variable | Description |
|---|---|
| `kappa` | Thermal conductivity [W/m/K] |

### 5.4.2 constAnIso

A constant, vector value (anistropic), is used for thermal conductivity.

| Variable | Description |
|---|---|
| `kappa` | Thermal conductivity (vector) [W/m/K] |

### 5.4.3 exponential

Thermal conductivity is calculated using an exponential function

$$
\kappa(T) = \kappa_0\left( \frac{T}{T_{ref}} \right)^{n_0}
$$
(5.84)

| Variable | Description |
|---|---|
| `kappa0` | Reference thermal conductivity [W/m/K] |
| $n_0$ | Exponential coefficient [ ] |
| $T_{ref}$ | Reference temperature [K] |

### 5.4.4 polynomial

Thermal conductivity is calculated using polynomial functions of temperature.

$$
\kappa(T) = \sum_{i=0}^{7} \kappa_iT^i
$$
(5.85)

| Variable | Description |
|---|---|
| `kappaCoeffs<8>` | Conductivity coefficients |

### 5.4.5 tabulatedIso

The tabulated, isotroptic solid transport model can be used to calculate the conductivity using the temperature. The data is read from a one dimensional table. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x" and "f" names are "T" and "kappa" respectively.

### 5.4.6 tabulatedAnIso

The tabulated, anisotroptic solid transport model can be used to calculate the conductivity using the temperature. The data is read from a one dimensional table. See Sec. 12.1 for more information on the available options for modifiers and interpolation schemes. The "x" and "f" names are "T" and "kappa" respectively.

## 5.5 Basic thermodynamic model

The basicFluid and basicSolid models ("type" basic) uses a transport model, thermodynamic model, and equation of state to describe a phase. The basic model should be used for non-reacting phases.

## 5.6 Detonating thermodynamic model

In order to better describe a detonating material, a 'detonating' thermodynamic model can be used. This model transitions between an unreacted state and a reacted state using an activation model. Each state (unreacted and reacted) is described by its own basic thermodynamic model, allowing for different models and coefficients to be used for values such as viscosity or specific heats. In addition to the activation model, afterburn models can also be used to add additional energy into the system after the initial detonation reaction has taken place.

This same methodology is applied to solid phases where energy is released locally to increase the thermal energy (internal energy). Only activation models are currenltly available.

Some standard combinations of unreacted and reacted equations of states include the JWL++ (Murnaghn and JWLC), and the blendedJWL (solidJWL and JWL).

> **NOTE:** Whilst it will not give the correct temperature, using an ideal gas is a simple option if the solid properties of the unreacted material are not known.

```cpp
phase1
{
    type detonating;
    reactants
    {
        thermoType
        {
            ...
        }
        ...
    }
    products
    {
        thermoType
        {
            ...
        }
        ...
    }
    activationModel linear;
    initiation
    {
        E0      9.0e9;
        points  ((0 0 0) (0.1 0.1 0.1));
        delays  (0 1e-5);
        radii   (0.001 0.005);
        vDet    5000;
    }
    afterburnModel Miller;
    MillerCoeffs
    {
        Q0      1e7;
        m       0.1667;
        n       0.5;
        a       0.0195e6;
        pMin    1.1e5;
    }
}
```

### 5.6.1 Activation Models

In order to accurately model the release of energy, different models can be used to approximate the speed at which the solid reactants become the product gases. The currently available models include the linear model, a pressure based model, and finally an Arrhenius rate reaction. Theses models all use a reaction progress variable, $\lambda_i$, to describe the state of individual cell activation. Additionally, in order to add numerical stability, the initial energy is defined using the unreacted equation of state, and the reaction energy, $E_0$, is added based on the time rate of change of the reaction progress variable, i.e.

$$
\dot{E} = E_0\frac{\rho_i}{\rho_{0,i}}\frac{d\lambda}{dt}
$$
(5.86)

The phase properties are calculated using

$$
x_i = \lambda^\ell_ix_{r,i} + (1 - \lambda^\ell_i)x_{u,i})
$$
(5.87)

where $x_{r,i}$ is the reacted phase quantity, $x_{u,i}$ is the unreacted phase quantity, and $\ell$ is the exponent used to blend the unreacted and reacted states (lambdaPow). By default $\ell$ is one. The advection scheme and limiters for $\lambda_i$ need to be specified in the fvSchemes in the same manner as the other transported quantities.

The setting of detonation points can be done for any activation model. By setting detonation points, the cells within the charge with the radii specified are set to full activated when run time reaches the given delays. If no radii are provided, only the cell containing the point will be activated. Additionally, delays can be used to specify the time at which the given point and cells within the radius are activated. For a single detonation point, the "useCOM" option can be used to calculate the center of mass of an individual charge.

Transport of the reaction progress variable is described by the transport equation

$$
\frac{\partial\alpha_i\rho_i\lambda_i}{\partial t} + \nabla\cdot(\alpha_i\rho_iu\lambda_i) = \alpha_i\rho_i\dot{R}_i
$$
(5.88)

where $\dot{R}_i$ is the reaction rate determined by the model of choice.

| Variable | Description |
|---|---|
| $E_0$ | Detonation energy [Pa] |
| `points` | Detonation points [m] |
| `radii` (`radius`) | Initiation radii around detonation points (default is 0) [m] |
| `delays` | Delay time of detonation points (default is 0) [s] |
| `lambdaPow` | Exponent used for blending [ ] (default is 1) |
| `useCOM` | Is the center of mass used as the detation point (default is no) |

#### 5.6.1.1 none

The none activation model assumes that all cells are activated when the simulation begins. This is the equivalent to an infinitely fast detonation velocity. The use of delays and detonation points are not valid here because the detonation is assumed to be instantaneous. There is no transport of the reaction progress variable.

#### 5.6.1.2 linear

The simplest activation model uses a list of detonation points and a constant detonation velocity to determine which cells have been activated. This gives

$$
\lambda_{i,j} = \begin{cases} 1 & \text{if } |x - x_{det,i,j}| < v_{det,i}t \\ 0 & \text{else} \end{cases}
$$
(5.89)

where $x$ is the cell center, $x_{det,i,j}$ is the jth detonation point, $v_{det,i}$ is the detonation velocity, and $t$ is the time. In order to account for multi-point detonation, the actual $\lambda$ is defined as

$$
\lambda_i = \max(\lambda_{i,j})
$$
(5.90)

| Variable | Description |
|---|---|
| `vDet` | Speed of propagation within the material [m/s] |

#### 5.6.1.3 programmedIgnition

The programmedIgnition activation model is slightly more complex than the linear activation model and includes the option to use activation due to compression of material, and is based on the work of Giroux (1973). The reaction progress variable is defined using a combination of two models, the compression

$$
\lambda_{\beta,i} = \frac{1 - \frac{\rho_{0,i}}{\rho_i}}{1 - V_{CJ,i}}
$$
(5.91)

where $V_{CJ,i}$ is the Chapman-Jougnuet specific volume which is computed using the Chapman-Jouguet pressure. The reference density, $\rho_{0,i}$ is read from the product equation of state. The programmed definition of the reaction progress variable is a modified version of the linear activation, where a cell reacts at a time-rate determined by the detonation velocity and the local grid size

$$
\lambda_{programmed,i} = \frac{\max(t - t_{ign,j}, 0)v_{det}}{1.5dx}
$$
(5.92)

where $t_{ign}$ is the time of ignition determined by the physical location and the detonation velocity, and $dx$ is the local grid size.

If the beta burn option is used, $\lambda_i = \lambda_{\beta,i}$; if the programmed burn option is used, $\lambda_i = \lambda_{programmed,i}$; and if the programmedBeta burn option is used $\lambda_i = \max(\lambda_{i,\beta}, \lambda_{programmed,i})$.

| Variable | Description |
|---|---|
| `vDet` | Speed of propagation within the material [m/s] |
| `Pcj` | Chapman-Jouguet pressure [Pa] |
| `burnModel` | Burn model used (beta, programmed, or programmedBeta) |

#### 5.6.1.4 pressureBased

A more advanced activation model uses the local cell pressure, determined by the equation of state, and follows the evolution equation

$$
\dot{R}_i = I\left( \frac{\rho_i}{\rho_{0,i}} - 1 - a \right)^x(1 - \lambda)^b + G_1(1 - \lambda)^c\lambda^dp^y + G_2(1 - \lambda)^e\lambda^fp^z
$$
(5.93)

The first term is responsible for the initial detonation based on the compression of the material. The following two terms account for the subsequent reaction based on the local pressure. All terms can be turned on or off by specifying the minimum and maximum values of lambda at which the stages occur.

| Variable | Description |
|---|---|
| $I$ | Ignition rate [s⁻¹] |
| `a` | Compression ratio offset [ ] |
| `b` | Ignition (1 − λ) exponent [ ] |
| `x` | Compression ratio exponent [ ] |
| `maxLambdaI` | Maximum value of λ that the ignition term is used [ ] |
| $G_1$ | First activation rate [Pa⁻ʸ s⁻¹] |
| `c` | First (1 − λ) exponent [ ] |
| `d` | First λ exponent [ ] |
| `y` | First pressure exponent [ ] |
| `minLambda1` | Minimum value of λ that the first step is used [ ] (default 0) |
| `maxLambda1` | Maximum value of λ that the first step is used [ ] (default 1) |
| $G_2$ | Second activation rate [Pa⁻ᶻ s⁻¹] |
| `e` | Second (1 − λ) exponent [ ] |
| `f` | Second λ exponent [ ] |
| `z` | Second pressure exponent [ ] |
| `minLambda2` | Minimum value of λ that the second step is used [ ] (default 0) |
| `maxLambda2` | Maximum value of λ that the second step is used [ ] (default 1) |
| `pScale` | Coefficient used to scale pressure [ ] (default is 1) |

#### 5.6.1.5 ArrheniusRate

A more physical representation of the activation rate uses the local temperature, defined by the internal energy and the specific heat of the mixture. The evolution equation for the reaction progress variable is

$$
\dot{R}_i = (1 - \lambda)\begin{cases} 0 & T < T_{ign} \\ d^2pA_{low}\exp\left( \frac{E_{a,low}}{RT} \right) & T_{ign} \le T < T_s \\ A_{high}\exp\left( \frac{E_{a,high}}{RT} \right) & T \ge T_s \end{cases}
$$
(5.94)

Where the particle diameter is determined by the chosen diameter model (see Sec. 9), and $R$ is the ideal gas constant.

| Variable | Description |
|---|---|
| `diameterModel` | Diameter model used to determine the particle diameter |
| $A_{Low}$ | Low activation rate [m⁻² s⁻¹] |
| $E_{aLow}$ | Low activation energy [m²/s²] |
| $A_{High}$ | High activation rate [s⁻¹] |
| $E_{aHigh}$ | High activation energy [m²/s²] |
| $T_s$ | Switch temperature [K] |
| $T_{ign}$ | Minimum temperature of reaction |

> **NOTE:** This model is still in development and has not been validated

### 5.6.2 Afterburn Models

When reactions occur over a period of time after the initial charge has been activated, additional energy can be added that results in higher pressure and temperature, and is refered to afterburn. Afterburn is typical in under-oxygenated and/or non-ideal explosives, which may release energy at a later time. The advection scheme and limiters for $c_i$ need to be specified in the fvSchemes in the same manner as the other transported quantities.

#### 5.6.2.1 none [default]

No additional energy is added. If the keyword "afterburnModel" is not found in the phase dictionary, this is the model that is used.

#### 5.6.2.2 constant

A constant amount of afterburn energy is added where $\dot{Q}$ is specified by the user.

| Variable | Description |
|---|---|
| `Qdot` | Afterburn energy addition rate[J/kg/s] |

#### 5.6.2.3 linear

Afterburn energy is added linearly from a start time to an end time where

$$
\dot{Q} = \begin{cases} \frac{Q_0}{\Delta t} & \text{if } t_{start} < t < t_{end} \\ 0 & \text{else} \end{cases}
$$
(5.95)

| Variable | Description |
|---|---|
| $Q_0$ | Afterburn energy [J/kg] |
| `tStart` | Time energy begins being added [s] |
| `tEnd` | Time energy stops being added [s] |

#### 5.6.2.4 Miller

The model of Miller (1995) uses an evolution equation to determine the fraction of the total amount of afterburn energy added to the system due to unburnt material. $c_i$ is the reaction progress variable that has a value between 0 and 1, with an evolution equation defined as

$$
\frac{\partial\alpha_i\rho_ic_i}{\partial t} + \nabla\cdot(\alpha_i\rho_iuc_i) = \alpha_i\rho_ia(1 - c_i)^m(p \times p_{scale})^n
$$
(5.96)

and the total afterburn energy is found using

$$
\dot{Q} = \frac{dc_i}{dt}Q_0
$$
(5.97)

| Variable | Description |
|---|---|
| `a` | Model constant [Pa⁻ⁿ] |
| `m` | Reaction progress variable exponent [ ] |
| `n` | Pressure exponent [ ] |
| $Q_0$ | Afterburn energy [J/kg] |
| `pMin` | Minimum pressure that afterburn occurs [Pa] |
| `pScale` | Scale factor for pressure (default is 1) [ ] |

## 5.7 Multicomponent thermodynamic model

The multicomponent fluid thermodynamic model allows for the use of multiple species that use the same equation of state by mass averaging equation of state coefficients of the species. The mass fractions of the species are required as initial conditions (Ydefault can be used to give initial conditions for multiple species). Additionally, a "defaultSpecie" must be provided in the thermodynamic dictionary to specify a slave specie

Below is an example of a multicomponent fluid

```cpp
type multicomponent;
species (ignitor air);
defaultSpecie air;
calculateDensity yes;
thermoType
{
    transport      const;
    thermo         eConst;
    equationOfState AbelNobel;
}
ignitor
{
    equationOfState
    {
        b    0.99e-3;
    }
    specie
    {
        molWeight      22.935;
    }
    transport
    {
        mu      1.81e-5;
        Pr      0.7;
    }
    thermodynamics
    {
        Cv      1450;
        Hf      1;
    }
}
air
{
    equationOfState
    {
        b    1.02e-3;
    }
    specie
    {
        molWeight      28.6689;
    }
    transport
    {
        mu      1.81e-5;
        Pr      0.7;
    }
    thermodynamics
    {
        Cv      1450;
        Hf      0;
    }
}
```

## 5.8 Two/multiphase models

To simulate a two-phase or multiphase system, the keyword "phases" must be defined in the phaseProperties dictionary and defines the list of phases used in a simulation. The selection of a two-phase or multiphase system is determined by the number of defined phases. The mixture pressure is defined by

$$
p = \frac{\sum_i \alpha_i\xi_ip_i}{\sum_i \alpha_i\xi_i}
$$
(5.98)

where

$$
\xi_i(\rho_i) = \frac{1}{\Gamma_i - 1}
$$
(5.99)

and $p_i$ is the pressure from a single equation of state (Zheng et al., 2011). The speed of sound within a given phase is given by

$$
c_i = \sqrt{\frac{\sum_i y_i\xi_ic^2_i}{\sum_i \xi_i}}
$$
(5.100)

with

$$
y_i = \frac{\alpha_i\rho_i}{\rho}
$$
(5.101)

Both the initial energy and temperature are calculated using a root finding method (Newton-Raphson by default) that include the contributions of all phases so the calculated values obey the mixture equations. See 12.3 for additional options.

## 5.9 Initialization

The initialization of fields can be handled in several ways, but $\rho_i$, $p$, and $T$ must be given as initial conditions. Some of these fields may be overwritten, but the boundary conditions are used to construct the conserved quantities. For equations of state in the Mie-Grüneisen form, by default the pressure and density are used to initialize the internal energy. Temperature based equations of state initialize the internal energy using the density and temperature. If the "calculateDensity" keyword is defined, and is set to "yes" in the given equation of state dictionary, then the density is calculated from the pressure and temperature prior to the initialization of the internal energy. Each of the initialization methods use a Newton-Raphson root finding method to find the necessary quantities. If the internal energy field is provided in the initial conditions folder, the pressure and temperature fields are calculated directly from the density and internal energy.

## 5.10 Example

An example of a single phase phaseProperties file can be seen below

```cpp
mixture
{
    type basic;
    calculateDensity yes;
    thermoType
    {
        transport      const;
        thermo         eConst;
        equationOfState idealGas;
    }
    transport
    {
        mu      0.0;
        Pr      1.0;
    }
    thermodynamic
    {
        Cv      718;
        Hf      0.0;
    }
    idealGas
    {
        gamma   1.4;
    }
}
```

For a two or multiphase simulation, the phaseProperies file is defined as

```cpp
phases (air water);
air
{
    type basic;
    thermoType
    {
        transport      const;
        thermo         eConst;
        equationOfState idealGas;
    }
    transport
    {
        mu      0.0;
        Pr      1.0;
    }
    thermodynamic
    {
        Cv      718;
        Hf      0.0;
    }
    equationOfState
    {
        gamma   1.4;
    }
}
water
{
    type basic;
    thermoType
    {
        transport      const;
        thermo         hConst;
        equationOfState stiffenedGas;
    }
    specie
    {
        molWeight      18.0;
    }
    transport
    {
        mu      0.0;
        Pr      1.0;
    }
    thermodynamic
    {
        Cp      4186;
        Hf      0.0;
    }
    equationOfState
    {
        gamma   4.4;
        a       7e8;
    }
}
```
