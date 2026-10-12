# Flux Evaluation

blastFoam relies on explicit solutions for the evolution of conservative variables.
This has several benefits in terms of order of accuracy and computational cost. First, higher-order, explicit Runge-Kutta time integration schemes can be used which allow for higher order time-integration accuracy. Secondly, because of the required time steps of the problems of interest, iterative matrix solutions are not necessary to ensure accuracy or stability. Instead, stability can be improved through use of SSP time integration methods or more restrictive limiters.

All of the methods currently available to calculate the conservative, hyperbolic fluxes rely on the owner (own) and neighbour (nei) interpolated values on a face (also called left and right states). These interpolated values are found using a combination of a base interpolation scheme and flux limiters. OpenFOAM currently has a wide selection of available limiters such as upwind, Minmod, vanLeer, SuperBee, etc. for scalars, and upwind, MinmodV, vanLeerV, SuperBeeV, etc. for vectors; all are run-time selectable.

In addition to the standard OpenFOAM interpolation schemes, MUSCL reconstruction has also been implemented. There are two main options which include upwindMUSCL and quadraticMUSCL. The upwind version uses standard upwinding for owner and neighbour interpolations. The quadratic version uses limiters in combination with the gradients and the gradient of the gradients (Hessians) to reconstruct face values. All of the standard limiters are available for MUSCL reconstruction. The vector limiters (MinmodV for example) are not used with the MUSCL schemes since the limiting is done for each component of the variables.

An example of the fvSchemes dictionary is shown below

```
fluxScheme HLLC;
ddtSchemes
{
    default Euler;
    timeIntegrator RK2SSP;
}
gradSchemes
{
    default cellMDLimited leastSquares 1.0;
}
divSchemes
{
    default none;
}
laplacianSchemes
{
    default Gauss linear corrected;
}
interpolationSchemes
{
    default
        linear;
    //Base interpolation scheme
    // Limiters
    reconstruct(alpha)
        vanLeer;
    // Volume fraction
    reconstruct(rho)
        upwindMUSCL;
    // Density
    reconstruct(p)
        linearMUSCL
        vanLeer; // Pressure
    reconstruct(U)
        quadraticMUSCL vanLeer; // Velocity
    reconstruct(e)
        quadraticMUSCL vanLeer; // Internal energy
    reconstruct(speedOfSound) vanLeer;
    // Speed of sound
}
```

NOTE: By default, if the OpenFOAM standard reconstruction is used, linear interpolation will be used. The limitWith method can instead be used to specify a different interpolation scheme such as cubic, but these have proven to be unstable in the past. Please use with caution.

## 10.1 Riemann Solvers

The currently available Riemann solvers are described below. For all schemes, $n$ denotes the surface normal vector, and $u = u \cdot n$. There is the inclusion of volume fraction in the solution of multi-fluid problems, however with the exception of the AUSM+up flux scheme for granular phases these changes will not be included in the descriptions below.

### 10.1.1 HLL

The HLL scheme is based on Toro et al. (1994) in which the contact wave is neglected. The fluxes take the form:

$$
F_{\mathrm{HLL}} = \begin{cases} F_{\mathrm{own}} & \text{if } 0 \leq S_{\mathrm{own}} \\ \dfrac{S_{\mathrm{nei}}F_{\mathrm{own}} - S_{\mathrm{own}}F_{\mathrm{nei}} + S_{\mathrm{own}}S_{\mathrm{nei}}(U_{\mathrm{nei}} - U_{\mathrm{own}})}{S_{\mathrm{nei}} - S_{\mathrm{own}}} & \text{if } S_{\mathrm{own}} \leq 0 \leq S_{\mathrm{nei}} \\ F_{\mathrm{nei}} & \text{if } 0 \geq S_{\mathrm{nei}} \end{cases}
$$
(10.1)

The owner and neighbor states to approximate the wave propagation speeds are defined as

$$
S_{\mathrm{own}} = \min(u_{\mathrm{own}} - c_{\mathrm{own}}, \tilde{u} - \tilde{c})
$$
(10.2)

$$
S_{\mathrm{nei}} = \max(u_{\mathrm{nei}} + c_{\mathrm{nei}}, \tilde{u} + \tilde{c})
$$
(10.3)

where $u_K$ is the normal flux of the respective state, $c_K$ is the speed of sound, and $\tilde{u}$ and $\tilde{c}$ are the Roe averages velocities and speed of sounds, respectively.

### 10.1.2 HLLC

The approximate HLLC Riemann was developed by Toro et al. (1994), and improves upon the HLL method by providing an estimation of the contact wave between the owner and neighbour waves. The specific implementation used is taken from Zheng et al. (2011, 2008) This means that the state between the owner and neighbour waves now has two states rather than one. The following fluxes are thus used, using the fact that both pressure and velocity are constant across the contact wave,

$$
F_{\mathrm{HLLC}} = \begin{cases} F_{\mathrm{own}} & \text{if } 0 \leq S_{\mathrm{own}} \\ F^*_{\mathrm{own}} & \text{if } S_{\mathrm{own}} \leq 0 \leq S^* \\ F^*_{\mathrm{nei}} & \text{if } S^* \leq 0 \leq S_{\mathrm{nei}} \\ F_{\mathrm{nei}} & \text{if } 0 \geq S_{\mathrm{nei}} \end{cases}
$$
(10.4)

The contact wave speed is given by

$$
S^* = \frac{\rho_{\mathrm{own}}u_{\mathrm{own}}(S_{\mathrm{own}} - U_{\mathrm{own}}) + \rho_{\mathrm{nei}}u_{\mathrm{nei}}(S_{\mathrm{nei}} - U_{\mathrm{nei}}) + p_{\mathrm{nei}} - p_{\mathrm{own}}}{\rho_{\mathrm{own}}(S_{\mathrm{own}} - u_{\mathrm{own}}) - \rho_{\mathrm{nei}}(S_{\mathrm{nei}} - u_{\mathrm{nei}})}
$$
(10.5)

and the pressure in the

$$
p_K^* = \rho_K(S_K - U_K)(S^* - u_K) + p_K
$$
(10.6)

The final fluxes are determined by

$$
F_K^{\mathrm{HLLC}*} = \frac{S^*(S_KU_K - F_K) + S_Kp_K^*D^*}{S_K - S^*}
$$
(10.7)

$$
D^* = \begin{pmatrix} 0 \\ \vdots \\ 0 \\ n \\ S^* \end{pmatrix}
$$
(10.8)

### 10.1.3 HLLCP

Following the work of Xie et al. (2019), a low-speed correction of the standard HLLC flux scheme has been added. Currently it is only available for single phase simulations.

$$
F_{\mathrm{HLLC-P}} = F_{\mathrm{HLLC}} + \Phi_P
$$
(10.9)

$$
\Phi_p = (f - 1)\frac{S_{\mathrm{own}}S_{\mathrm{nei}}}{S_{\mathrm{nei}} - S_{\mathrm{own}}}\frac{1}{1 + |\tilde{M}|}\frac{p_{\mathrm{nei}} - p_{\mathrm{own}}}{\tilde{c}^2}\begin{pmatrix} 1 \\ \tilde{u} \\ \frac{1}{2}\tilde{u}^2 \end{pmatrix}
$$
(10.10)

$$
f = \min\left(\frac{p_{\mathrm{own}}}{p_{\mathrm{nei}}}, \frac{p_{\mathrm{nei}}}{p_{\mathrm{own}}}\right)^3
$$
(10.11)

where the minimum of all cell faces is used for each cell.

$$
p^{**} = \theta p^* + (1 - \theta)\frac{p_{\mathrm{own}} + p_{\mathrm{nei}}}{2}
$$
(10.12)

$$
\theta = \min(M^*, 1)
$$
(10.13)

$$
p^{***} = fp^{**} + (1 - f)p^*
$$
(10.14)

where $p^{***}$ replaces $p_K^*$ in Eq. (10.7)

### 10.1.4 AUSM+

The AUSM+ scheme was developed by Luo et al. (2004) and constructs the fluxes based on the mass flux across the face.

$$
F_{\mathrm{AUSM+}} = 0.5[M^*c^*(U_{\mathrm{own}} + U_{\mathrm{nei}})] - 0.5[|M^*|c^*(U_{\mathrm{own}} + U_{\mathrm{nei}})] + F_p
$$
(10.15)

$$
F_p = \begin{pmatrix} 0 \\ \vdots \\ 0 \\ p^*n \\ p^* \end{pmatrix}
$$
(10.16)

The star state variables are written as

$$
c^* = 0.5(c_{\mathrm{own}} + c_{\mathrm{nei}})
$$
(10.17)

$$
M^* = M_{4,\mathrm{own}}^+ + M_{4,\mathrm{nei}}^-
$$
(10.18)

and

$$
P^* = P_{5,\mathrm{own}}^+p_{\mathrm{own}} + P_{5,\mathrm{nei}}^-p_{\mathrm{nei}}
$$
(10.19)

where

$$
M_1^\pm(M) = 0.5(M \pm |M|)
$$
(10.20)

$$
M_2^\pm(M) = \begin{cases} M_1^\pm(M) & \text{if } |M| \geq 1 \\ \pm 0.25(M \pm 1)^2 & \text{else} \end{cases}
$$
(10.21)

$$
M_4^\pm(M) = \begin{cases} M_1^\pm(M) & \text{if } |M| \geq 1 \\ M_2^\pm(M)\left[1 \mp 16\beta M_2^\mp(M)\right] & \text{else} \end{cases}
$$
(10.22)

$$
P_5^\pm(M) = \begin{cases} \frac{1}{M}M_1^\pm(M) & \text{if } |M| \geq 1 \\ \pm M_2^\pm(M)\left[(2 \mp M) - 16\alpha M M_2^\mp(M)\right] & \text{else} \end{cases}
$$
(10.23)

with $\alpha = 3/16$ and $\beta = 1/8$.

### 10.1.5 AUSM+up

The AUSM+ scheme extended to include a low speed correction by Liou (2006). The previous section is used to describe the high speed portion, however additional diffusion terms are added resulting in the following definitions of the mass and pressure fluxes

$$
M^* = M_{4,\mathrm{own}}^+ + M_{4,\mathrm{nei}}^- + M_p
$$
(10.24)

and

$$
P^* = P_{5,\mathrm{own}}^+p_{\mathrm{own}} + P_{5,\mathrm{nei}}^-p_{\mathrm{nei}} + P_u
$$
(10.25)

where

$$
M_p = -K_p\frac{f_a}{\max(1 - \sigma\bar{M}_a^2, 0)}\frac{p_{\mathrm{nei}} - p_{\mathrm{own}}}{\rho^*c_*^2}
$$
(10.26)

$$
P_u = -K_uP_{5,\mathrm{own}}^+P_{5,\mathrm{nei}}^-(\rho_{\mathrm{own}} + \rho_{\mathrm{nei}})f_ac^*(u_{\mathrm{nei}} - u_{\mathrm{own}})
$$
(10.27)

and $f_a = 1$, $\sigma = 1$, $K_p = 0.25$, $K_u = 0.75$, and $\alpha$ is redefined as $\frac{3}{16(5f_a - 4)}$. The interface density, $\rho^*$, is defined as $\frac{\rho_{\mathrm{own}}+\rho_{\mathrm{nei}}}{2}$, and the average Mach number is defined as.

$$
\bar{M}_a^2 = \sqrt{\frac{u_{\mathrm{own}}^2 + u_{\mathrm{nei}}^2}{2c_*^2}}
$$
(10.28)

This correction is very important when considering blasts because the Mach numbers can become much less than unity, resulting in numerical checker-boarding.

### 10.1.6 AUSM+up (granular)

A modified version of the AUSM+up flux scheme has been developed by Houim and Oran (2016) and includes flux limiters in the event of packing. The flux of conservative variables, (mass, momentum, thermal energy, and granular energy) across a face is given by

$$
F_s^{\mathrm{AUSM+up}} = F_p + \dot{m}\begin{cases} U_{\mathrm{own}} & \text{if } \dot{m} > 0 \\ U_{\mathrm{nei}} & \text{if } \dot{m} \leq 0 \end{cases}
$$
(10.29)

where

$$
\dot{m} = Fc_{1/2}M_{1/2}\begin{cases} \alpha_{\mathrm{own}}\rho_{\mathrm{own}} & \text{if } M_{1/2} > 0 \\ \alpha_{\mathrm{nei}}\rho_{\mathrm{nei}} & \text{if } M_{1/2} \leq 0 \end{cases}
$$
(10.30)

$$
F = (c_{1/2} - \epsilon)[1 + |M_{1/2}|(1 - G/2)]^2\frac{\max(\alpha_{s,\mathrm{own}}, \alpha_{s,\mathrm{nei}})}{\alpha_{s,\mathrm{max}}}[\alpha_{\mathrm{own}}\rho_{\mathrm{own}} - \alpha_{\mathrm{nei}}\rho_{\mathrm{nei}}]
$$
(10.31)

and $F_p = \left(0, P_{\mathrm{tot},1/2}I, 0, 0\right)$, with $\alpha_s$ being the total granular volume fraction (sum of all granular phases), $\alpha_{s,\mathrm{max}}$ being the maximum volume fraction at which packing occurs, and $\epsilon$ being a small number (1e-10). $G$ is defined as

$$
G = \max(2(1 - D\zeta^2))
$$
(10.32)

and $\zeta$ is defined as

$$
\zeta = \begin{cases} \dfrac{\alpha_s^M - \alpha_{s,\mathrm{crit}}}{\alpha_{s,\mathrm{max}} - \alpha_{s,\mathrm{crit}}} & \text{if } \alpha_s^M > \alpha_{s,\mathrm{crit}} \\ 0 & \text{if } \alpha_s^M < \alpha_{s,\mathrm{crit}} \end{cases}
$$
(10.33)

where $\alpha_s^M$ is the maximum granular volume fraction of the own/nei value, and $\alpha_{s,\mathrm{crit}}$ being the minimum granular volume fraction that frictional stresses occur. $c_{1/2}$ is defined as

$$
c_{1/2} = \sqrt{\frac{\alpha_{\mathrm{own}}\rho_{\mathrm{own}}c_{\mathrm{own}}^2 + \alpha_{\mathrm{nei}}\rho_{\mathrm{nei}}c_{\mathrm{nei}}^2}{\alpha_{\mathrm{own}}\rho_{\mathrm{own}} + \alpha_{\mathrm{nei}}\rho_{\mathrm{nei}}} + \epsilon}
$$
(10.34)

The split Mach number is defined as

$$
M_{1/2} = M_{4,\mathrm{own}}^+ + M_{4,\mathrm{nei}}^- - \frac{2K_p}{f_a}\max(1 - \sigma\bar{M}^2, 0)\frac{P_{\mathrm{tot,nei}} - P_{\mathrm{tot,own}}}{(\alpha_{\mathrm{own}}\rho_{\mathrm{own}} + \alpha_{\mathrm{nei}}\rho_{\mathrm{nei}} + \epsilon)c_{1/2}^2}
$$
(10.35)

where $M_4^\pm$ is calculate the same way as in the AUSM+ scheme and $f_a = 1$. $K_p$, and $\sigma$ are defined as

$$
K_p = 0.25 + 0.75(1 - G/2)
$$
(10.36)

$$
\sigma = 0.75\sigma/2
$$
(10.37)

The pressure is defined as

$$
P_{\mathrm{tot},1/2} = -K_uf_a(c_{1/2} - \epsilon)P_{5,\mathrm{own}}^+P_{5,\mathrm{nei}}^-(\alpha_{\mathrm{own}}\rho_{\mathrm{own}} + \alpha_{\mathrm{nei}}\rho_{\mathrm{nei}})(u_{\mathrm{nei}} - u_{\mathrm{own}}) + P_{5,\mathrm{own}}^+p_{\mathrm{tot,own}} + P_{5,\mathrm{nei}}^-p_{\mathrm{tot,nei}}
$$
(10.38)

with $P_5^\pm$ being the same as in the AUSM+ scheme and

$$
K_u = 0.75 + 0.25(1 - G/2)
$$
(10.39)

### 10.1.7 Tadmor/Kurganov

The Tadmor/Kurganov fluxes were developed by Kurganov and Tadmor (2000). The rhoCentalFoam solver (OpenCFD Ltd., 2018a; Greenshields et al., 2010) utilizes this scheme, which has been ported to the current framework. Two run-time selectable options (e.g. Kurganov or Tadmor) are available; both follow the same general procedure with a slight difference in the calculation of coefficients.

The Kurganov scheme defines

$$
a^+ = \max(\max(u_{\mathrm{own}} + c_{\mathrm{own}}, u_{\mathrm{nei}} + c_{\mathrm{nei}}), 0)
$$
(10.40)

$$
a^- = \min(\min(u_{\mathrm{own}} - c_{\mathrm{own}}, u_{\mathrm{nei}} - c_{\mathrm{nei}}), 0)
$$
(10.41)

$$
a_{\mathrm{own}} = \frac{a^+}{a^+ + a^-}
$$
(10.42)

$$
a_{\mathrm{nei}} = \frac{a^-}{a^+ + a^-}
$$
(10.43)

and

$$
a = \frac{a^-a^+}{a^+ + a^-}
$$
(10.44)

The Tadmor scheme defines $a_{\mathrm{own}} = a_{\mathrm{nei}} = 0.5$ and $a = \max(|a^-|, |a^+|)$. The volumetric fluxes are written

$$
\phi_{\mathrm{own}} = u_{\mathrm{own}}a_{\mathrm{own}} - a
$$
(10.45)

and

$$
\phi_{\mathrm{nei}} = u_{\mathrm{nei}}a_{\mathrm{nei}} + a
$$
(10.46)

The resulting fluxes are

$$
F_{KT} = (\phi_{\mathrm{own}}U_{\mathrm{own}} + \phi_{\mathrm{nei}}U_{\mathrm{nei}}) + F_p
$$
(10.47)

with

$$
F_p = \begin{pmatrix} 0 \\ \vdots \\ 0 \\ (a_{\mathrm{own}}p_{\mathrm{own}} + a_{\mathrm{nei}}p_{\mathrm{nei}})n \\ a(p_{\mathrm{own}} - p_{\mathrm{nei}}) \end{pmatrix}
$$
(10.48)

## 10.2 Riemann advection scheme

In order to allow for consistency between the conserved quantities (mass, momentum, and energy), and additional transport quantities such as turbulence fields or species mass fractions, an additional advection scheme using the Riemann fluxes has been added. This makes use of the quantities calculated in transport of the conserved variable which then allows for the use of higher order interpolation schemes to be used for additional scalar transport. This is a major advantage over traditional methods which are generally limited to upwinding for additional transport due to presence of strong gradients.

```
divSchemes
{
    default
        none;
    div(alphaRhoPhi.tnt,lambda.tnt)
        Riemann;
    div(alphaRhoPhi.tnt,c.tnt)
        Riemann;
}
interpolationSchemes
{
    default linear;
    ...
    reconstruct(lambda.tnt)
        linearMUSCL vanLeer;
    reconstruct(c.tnt)
        linearMUSCL vanLeer;
}
```

In the interpolation schemes sub-dictionary, the limiters should be specified for each field using the Riemann fluxes, but by default the limiter specified by "reconstruct(rho)" will be used.

NOTE: One limitation of using the Riemann fluxes is that, because an explicit advection term for the transported quantities is used, when very stiff implicit terms are present (such as production term in turbulence models), the advection term can become negligible leading to no advection occurring. For this reason, implicit divergence schemes are still recommended for the advection of turbulence quantities and other equations with large implicit source terms.

## 10.3 Time integration

Higher order time integration has been added allowing for fully third order accurate solutions to the evolution equations. This is a major benefit in comparison to standard OpenFOAM time integration which is at most second order due to the limitation on the implicit time evolution. This functionality applies to both conservative quantities such as mass, momentum, and energy, as well as the activation and afterburn models. The transport of turbulent quantities are still limited by the standard time integration schemes in OpenFOAM. Below are the currently available time integration schemes and the mathematical steps associated with them. The superscript $n$ denotes the state at the beginning of the current time step, $(i)$ denotes the $i$-th step, and $n + 1$ denotes final state. The time integration scheme is specified in the fvSchemes dictionary using

```
ddtSchemes
{
    default Euler;
    timeIntegrator RK2SSP 3; // Three stages, second order accurate
}
```

NOTE: The strong stability preserving (SSP) methods offer several different variation that allow for a greater number of steps to be used to add additional stability to the solution. This is specified by adding the number of requested steps after the SSP scheme. If a number is provided that is higher or lower than the available number of steps, the scheme will used the closest number of steps.

### 10.3.1 Euler

Standard first order time integration

$$
U^{n+1} = U^n - \Delta t\nabla\cdot F^n
$$
(10.49)

### 10.3.2 RK1SSP

First-order, strong-stability-preserving Runge-Kutta method (Spiteri and Ruuth, 2002):

One stage:

$$
U^{n+1} = U^n - \Delta t\nabla\cdot F^n
$$
(10.50)

Two stages:

$$
U^{(1)} = U^n - \frac{1}{2}\Delta t\nabla\cdot F^n
$$
(10.51)

$$
U^{n+1} = \frac{1}{2}U^{(1)} - \frac{1}{2}\Delta t\nabla\cdot F^{(1)}
$$
(10.52)

Three stages:

$$
U^{(1)} = U^n - \frac{1}{3}\Delta t\nabla\cdot F^n
$$
(10.53)

$$
U^{(2)} = U^{(1)} - \frac{1}{3}\Delta t\nabla\cdot F^{(1)}
$$
(10.54)

$$
U^{n+1} = U^{(2)} - \frac{1}{3}\Delta t\nabla\cdot F^{(2)}
$$
(10.55)

### 10.3.3 RK2

Standard second-order Runge-Kutta method (mid point):

$$
U^{(1)} = U^n - \frac{1}{2}\Delta t\nabla\cdot F^n
$$
(10.56)

$$
U^{n+1} = U^n - \Delta t\nabla\cdot F^{(1)}
$$
(10.57)

### 10.3.4 RK2SSP

Second-order, strong-stability-preserving Runge-Kutta method (Spiteri and Ruuth, 2002):

Two stages:

$$
U^{(1)} = U^n - \Delta t\nabla\cdot F^n
$$
(10.58)

$$
U^{n+1} = \frac{1}{2}\left(U^n + U^{(1)} - \Delta t\nabla\cdot F^{(1)}\right)
$$
(10.59)

Three stages:

$$
U^{(1)} = U^n - \frac{1}{2}\Delta t\nabla\cdot F^n
$$
(10.60)

$$
U^{(2)} = U^{(1)} - \frac{1}{2}\Delta t\nabla\cdot F^{(1)}
$$
(10.61)

$$
U^{n+1} = \frac{1}{3}U^n + \frac{2}{3}U^{(1)} - \frac{1}{3}\Delta t\nabla\cdot F^{(2)}
$$
(10.62)

Four stages:

$$
U^{(1)} = U^n - \frac{1}{3}\Delta t\nabla\cdot F^n
$$
(10.63)

$$
U^{(2)} = U^{(1)} - \frac{1}{3}\Delta t\nabla\cdot F^{(1)}
$$
(10.64)

$$
U^{(3)} = U^{(2)} - \frac{1}{3}\Delta t\nabla\cdot F^{(2)}
$$
(10.65)

$$
U^{n+1} = \frac{1}{4}U^n + \frac{3}{4}U^{(3)} - \frac{1}{4}\Delta t\nabla\cdot F^{(3)}
$$
(10.66)

### 10.3.5 RK3SSP

Third-order, strong-stability-preserving Runge-Kutta method (Spiteri and Ruuth, 2002):

Three stages:

$$
U^{(1)} = U^n - \Delta t\nabla\cdot F^n
$$
(10.67)

$$
U^{(2)} = \frac{1}{4}\left(3U^n + U^{(1)} - \Delta t\nabla\cdot F^{(1)}\right)
$$
(10.68)

$$
U^{n+1} = \frac{1}{3}\left(U^n + 2U^{(2)} - 2\Delta t\nabla\cdot F^{(1)}\right)
$$
(10.69)

Four stages:

$$
U^{(1)} = U^n - \frac{1}{2}\Delta t\nabla\cdot F^n
$$
(10.70)

$$
U^{(2)} = U^{(1)} - \frac{1}{2}\Delta t\nabla\cdot F^{(1)}
$$
(10.71)

$$
U^{(3)} = \frac{2}{3}U^n + \frac{1}{3}U^{(2)} - \frac{1}{6}\Delta t\nabla\cdot F^{(2)}
$$
(10.72)

$$
U^{n+1} = U^{(3)} - \frac{1}{2}\Delta t\nabla\cdot F^{(3)}
$$
(10.73)

### 10.3.6 RK4

Standard fourth-order Runge-Kutta method:

$$
U^{(1)} = U^n - \frac{1}{2}\Delta t\nabla\cdot F^n
$$
(10.74)

$$
U^{(2)} = U^{(1)} - \frac{1}{2}\Delta t\nabla\cdot F^{(1)}
$$
(10.75)

$$
U^{(3)} = U^n - \Delta t\nabla\cdot F^{(2)}
$$
(10.76)

$$
U^{n+1} = U^n - \frac{1}{6}\Delta t\nabla\cdot\left(F^n + 2F^{(1)} + 2F^{(2)} + F^{(3)}\right)
$$
(10.77)

### 10.3.7 RK4SSP

Fourth-order, strong-stability-preserving Runge-Kutta method (Spiteri and Ruuth, 2002):

$$
U^{(i)} = \sum_{k=0}^{i-1}\left(a_{ik}U^{(k)} + \Delta t\beta_{ik}\nabla\cdot F^{(k)}\right)
$$
(10.78)

Table 1: $a_{ik}$

|   | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| 1 | 649/1600 | 951/1600 |  |  |
| 2 | 53989/2500000 | 4806213/20000000 | 23619/32000 |  |
| 3 | 1/5 | 6127/30000 | 7873/30000 | 1/3 |

Table 2: $\beta_{ik}$

|   | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| 1 | 1 | −10890423/25193600 | 5000/7873 |  |
| 2 | −102261/5000000 | −5121/20000 | 7873/10000 |  |
| 3 | 1/10 | 1/6 | 0 | 1/6 |
