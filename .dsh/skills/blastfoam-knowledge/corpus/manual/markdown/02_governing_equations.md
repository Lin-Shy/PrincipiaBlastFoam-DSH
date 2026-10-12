# Governing equations

Here the governing conservation equations used within blastFoam will be described.

We will describe two cases: (1) the single-fluid case where a single shared velocity and energy is used and (2) the multi-fluid case where each fluid has a unique velocity and energy. The phrase "multi-phase" will be used to denote a fluid that uses multiple equations of states to describe the density-energy-pressure relation.

For both variations $U$ is the vector of conservative variables, $F$ are the fluxes corresponding to the respective conservative variables, and $S$ is a vector of source terms,

$$
∂_t U + ∇ · F = S
$$

(2.1)

The exact form each of these take will depend on whether the single-fluid or multi-fluid is used. Each of these are presented in the following sections.

## 2.1 Single-fluid model

For a single phase with multiple species, the conservative variables and fluxes are defined as

$$
U = \begin{pmatrix} ρ \\ ρ Y_s \\ ρu \\ ρE \end{pmatrix}
$$

(2.2)

$$
F = \begin{pmatrix} ρu \\ ρ Y_s u \\ ρu ⊗ u + pI \\ (ρE + p)u \end{pmatrix}
$$

(2.3)

$$
S = \begin{pmatrix} 0 \\ \dot{R}_s + ∇ · J_s \\ \dot{M} + \dot{M}_v \\ \dot{E} + \dot{E}_v \end{pmatrix}
$$

(2.4)

where $Y_s$ is the mass fraction of specie $s$, and $J_s$ is the diffusion flux of species $s$. For multiple phases

$$
U = \begin{pmatrix} α_1 \\ \vdots \\ α_n \\ α_1 ρ_1 \\ \vdots \\ α_n ρ_n \\ ρu \\ ρE \end{pmatrix}
$$

(2.5)

$$
F = \begin{pmatrix} α_1 u \\ \vdots \\ α_n u \\ α_1 ρ_1 u \\ \vdots \\ α_n ρ_n u \\ ρu ⊗ u + pI \\ (ρE + p)u \end{pmatrix}
$$

(2.6)

$$
S = \begin{pmatrix} α_1 ∇ · u \\ \vdots \\ α_n ∇ · u \\ 0 \\ \vdots \\ 0 \\ \dot{M} + \dot{M}_v \\ \dot{E} + \dot{E}_v \end{pmatrix}
$$

(2.7)

where $ρ$ is the mixture density, $u$ is the mixture velocity, $E$ is the total energy (thermal and kinetic), $p$ is the pressure, and $ρ_i$ and $α_i$ are the density and volume fraction of each phase.

The source terms, $\dot{R}_s$, $\dot{M}$, and $\dot{E}$ are the specie production from reactions, momentum, and energy sources (including gravitational acceleration), and $\dot{M}_v$ and $\dot{E}_v$ are viscous terms.

The sum of all volume fractions is defined to be one, i.e.

$$
\sum_i α_i = 1
$$

(2.8)

When only two phases are used, the second volume fraction is defined

$$
α_2 = 1 − α_1
$$

(2.9)

Additionally, the mixture density is defined by

$$
ρ = \sum_i α_i ρ_i
$$

(2.10)

When all phases are considered inviscid, $\dot{M}_v = \dot{E}_v = 0$. However, when viscosity is included,

$$
\dot{M}_v = ∇ · \left( ρν \left[ ∇u + (∇u)^⊺ − \frac{2}{3}(∇ · u)I \right] \right)
$$

(2.11)

and

$$
\dot{E}_v = ∇ · \left( ρν \left[ ∇u + (∇u)^⊺ − \frac{2}{3}(∇ · u)I \right] · u \right) + ∇ · (α_T ∇e)
$$

(2.12)

where $ν$ is the viscosity, $α_T$ is the thermal diffusivity, and $I$ is the identity matrix.

The five equation model is used for multiphase systems in which a single shared velocity, a shared internal energy and temperature is used, and individual phase masses are conserved. Pressure is defined using a specified EOS, where the mixture's internal energy, densities, and volume fraction are used to calculate the total pressure.

## 2.2 Multi-fluid

Similar to flows that use a single shared velocity and energy, the mass, momentum, and energy are all conserved. In contrast, however, each phase has its own set of mass, momentum, and energy, which is transferred between phases using interfacial transfer models (such as drag, heat transfer, etc.).

The conservation equations for the $i$th fluid phase are

$$
U_i = \begin{pmatrix} α_i \\ α_i ρ_i \\ α_i ρ_i u_i \\ α_i ρ_i E_i \end{pmatrix}
$$

(2.13)

$$
F = \begin{pmatrix} α_i u_i \\ α_i ρ_i u_i \\ α_i ρ_i u_i ⊗ u_i + α_i p_i I \\ α_i (ρ_i E_i + p_i) u_i \end{pmatrix}
$$

(2.14)

$$
S = \begin{pmatrix} α_i ∇ · u_i + \sum_{i \ne j} \dot{ω}_{ij} I(ρ_i, ρ_j) \\ \sum_{i \ne j} \dot{ω}_{ij} \\ α_i ρ_i g + \sum_{i \ne j} \dot{M}_{ij} + \dot{M}_{v,i} \\ α_i ρ_i g · u_i + \sum_{i \ne j} (\dot{E}_{ij} + \dot{M}_{ij} · u_{int,ij}) + \dot{E}_{det,i} + \dot{E}_{v,i} \end{pmatrix}
$$

(2.15)

where $α_i$ is the phase volume fraction, $ρ_i$ is the phase density, $u_i$ is the phase velocity, $E_i$ is the total phase energy, and $p_i$ is the phase pressure. The source terms, $\dot{M}_{ij}$ and $\dot{E}_{ij}$, are the momentum and energy sources that account for interactions between other phases, $\dot{M}_{v,i}$ and $\dot{E}_{v,i}$ are viscous terms, $g$ is the gravitational acceleration vector, $\dot{E}_{det,i}$ is the energy added due to reactions, and $u_{int,ij}$ is the interfacial velocity between two phases. When mass transfer is used $\dot{ω}_{i,j}$ is the mass transfer rate from the $i$th phase to the $j$th phase, and $I$ is a switching function used to select the transferring quantity (Xue et al., 2011) and is defined as

$$
I(x_i, x_j) = ξ_{i,j} x_j + (1 − ξ_{i,j}) x_i
$$

(2.16)

and

$$
ξ_{i,j} = \begin{cases} 1 & \text{if } \dot{ω}_{i,j} > 0 \\ 0 & \text{else} \end{cases}
$$

(2.17)

The viscous stress uses a Newtonian stress tensor defined as

$$
\dot{M}_{v,i} = ∇ · \left( α_i ρ_i ν_i \left[ ∇u_i + (∇u_i)^⊺ − \frac{2}{3}(∇ · u_i)I \right] \right)
$$

(2.18)

and

$$
\dot{E}_{v,i} = ∇ · \left( α_i ρ_i ν_i \left[ ∇u_i + (∇u_i)^⊺ − \frac{2}{3}(∇ · u_i)I \right] · u_i \right) + ∇ · (α_i α_{T,i} ∇e_i)
$$

(2.19)

where $ν_i$ is the viscosity, $α_{T,i}$ is the thermal diffusivity, and $I$ is the identity matrix.

The momentum transfer term, $\dot{M}_{ij}$, is defined as

$$
\dot{M}_{ij} = \dot{M}_{D,ij} + \dot{M}_{L,ij} + \dot{M}_{VM,ij} + \dot{M}_{WL,ij} + \dot{M}_{TD,ij} + \dot{ω}_{i,j} I(u_i, u_j)
$$

(2.20)

where the summed terms, in order, represent drag, lift, virtual mass, wall lubrication, and turbulent dispersion, respectively.

The energy transfer term, $\dot{E}_{ij}$, is defined as

$$
\dot{E}_{ij} = \dot{E}_{HT,ij} + \dot{ω}_{i,j} I(E_i, E_j + hf_i − hf_j)
$$

(2.21)

where $\dot{E}_{HT,ij}$ is the energy transfer rate due to convective heat transfer, and $hf$ is the heat of formation.

### 2.2.1 Granular phases

In contrast to a standard fluid (gas or liquid), a granular fluid tracks the phase mass, momentum, thermal energy, and granular energy. The last quantity, granular energy, is the energy that is present due to fluctuation in the phase velocity within a cell. This is the kinetic energy due to the local velocity variance. The more common quantity is the granular temperature, $Θ_i$, which is related to the granular energy by $⟨E⟩_i = \frac{3}{2} Θ_i$. The governing equations are

$$
U_i = \begin{pmatrix} α_i ρ_i \\ α_i ρ_i u_i \\ α_i ρ_i e_i \\ α_i ρ_i ⟨E⟩_i \end{pmatrix}
$$

(2.22)

$$
F = \begin{pmatrix} α_i ρ_i u_i \\ α_i ρ_i u_i ⊗ u_i + (P_{s,i} + P_{fric,i})I \\ α_i ρ_i e_i u_i \\ α_i ρ_i u_i ⟨E⟩_i \end{pmatrix}
$$

(2.23)

$$
S = \begin{pmatrix} \sum_{i \ne j} \dot{ω}_{ij} \\ α_i ρ_i g − α_i \sum_{\ell} ∇p_{int,i\ell} + \sum_j \dot{M}_{ij} + \dot{M}_{v,i} \\ \sum_j \dot{e}_{ij} + \sum_k \dot{γ}_{ik} + \dot{e}_{det,i} \\ −\sum_k \dot{γ}_{ik} − \sum_{\ell} φ_{prod,i\ell} − P_{s,i} ∇ · u_i + α_i τ_i : ∇u_i + ∇ · (κ_{s,i} ∇Θ_i) + \sum_{i \ne j} \dot{ω}_{ij} I(⟨E⟩_i, 0) \end{pmatrix}
$$

(2.24)

where, again, $α_i$ is the phase volume fraction, $ρ_i$ is the phase density, $u_i$ is the phase velocity, and $e_i$ is the phase thermal energy. The summations $\sum_j$, $\sum_k$, and $\sum_{\ell}$ denote summations over all phases, all solid phases, and all fluid phases, respectively. The new quantities, $P_{s,i}$, $P_{fric,i}$, $⟨E⟩$, and $p_{int}$ are the granular pressure, frictional pressure, granular energy, and interfacial pressure (generally taken as the gas phase pressure), respectively. The density is assumed to be constant, so the volume fraction is found by simply dividing the total phase mass by the known density. The source terms, $\dot{M}_{ij}$, $\dot{e}_{ij}$, $\dot{γ}_{ij}$, and $φ_{prod,il}$ are the momentum transfer, energy transfer, granular energy dissipation, and production terms. The momentum and energy transfer terms are the same as for a fluid phase ($\dot{e}_{ij} = \dot{E}_{ij}$ and $\dot{e}_{det,i} = \dot{E}_{det,i}$). The production and dissipation terms are described below.

The production and dissipation of granular energy introduce a new term into the continuous phase total energy equation so that the continuous phase source terms become

$$
S = \begin{pmatrix} α_i ∇ · u_i + \sum_{i \ne j} \dot{ω}_{ij} I(ρ_i, ρ_j) \\ \sum_{i \ne j} \dot{ω}_{ij} \\ α_i ρ_i g + \sum_{i \ne j} \dot{M}_{ij} + \dot{M}_{v,i} \\ α_i ρ_i g · u_i + \sum_{i \ne j} \dot{E}_{ij} + \dot{E}_{det,i} + \dot{E}_{v,i} + \sum_k φ_{prod,k} \\ \sum_k \dot{ω}_{ik} I(0, ⟨E⟩_k) \end{pmatrix}
$$

(2.25)

You can also see in Eq. (2.22) that the dissipation of granular energy is converted into thermal energy within the solid phase. For those familiar with incompressible flows, this term is typically neglected due to the fact that the amount of heat produced from collisions is typically very small. In highly compressible flows, this is not the case, and significant heat can be generated due to the loss of energy from inelastic collisions.

We define the change in momentum due to granular phase stress as

$$
\dot{M}_{ij} = ∇ · τ_{s,i} + \dot{ω}_{i,j} I(u_i, u_j)
$$

(2.26)

and the granular stress is defined as

$$
τ_{s,i} = ρ_i ν_{s,i} [∇u_i + (∇u_i)^⊺] + \left( λ_{s,i} − \frac{2}{3} ρ_i ν_{s,i} \right) (∇ · u_i)I
$$

(2.27)

with $λ_{s,i}$ being the bulk viscosity of the granular phase defined by (Huilin and Gidaspow, 2003)

$$
λ_{s,i} = \sum_k \left( \frac{P_{s,ik}}{d_{ik}} \right) 3 \sqrt{\frac{2(m_i Θ_i + m_k Θ_k)^2}{π Θ_i Θ_k (m_i^2 Θ_i + m_k^2 Θ_k)}}
$$

(2.28)

where $P_{s,ij}$ is the granular pressure between solid phases $i$ and $k$, and is related to $P_{s,i}$ by

$$
P_{s,i} = α_i ρ_i Θ_i + \sum_k P_{s,ik}
$$

(2.29)

The production of granular energy is given by

$$
φ_{prod,i\ell} = \frac{81 α_i µ_{\ell}^2 g_{0,ii}}{d_i^3 ρ_i \sqrt{π}} \frac{|u_{\ell} − u_i|^2}{\sqrt{Θ_i}} − 3 K_{D,i\ell} Θ_i
$$

(2.30)

where $K_{D,i\ell}$ is the drag coefficient for the $i$-$\ell$ solid-fluid pair and $g_{0,ij}$ is the radial distribution function.

The dissipation of granular energy between granular phases $i$ and $k$ is defined by (Huilin and Gidaspow, 2003)

$$
\dot{γ}_{ik} = \left[ \frac{3}{d_{ik}} \sqrt{\frac{2 m_0^2 Θ_i Θ_k}{π(m_i^2 Θ_i + m_k^2 Θ_k)}} − \frac{3 m_0 (m_i Θ_i + m_k Θ_k)}{4(m_i^2 Θ_i + m_k^2 Θ_k)} ∇ · u_i \right] (1 − e_{ik}) P_{s,ik}
$$

(2.31)

where

$$
m_i = \frac{ρ_i π d_i^3}{6}
$$

(2.32)

$d_{ik} = (d_i + d_k)/2$, $m_0 = m_i + m_k$, $e_{ik}$ is the coefficient of restitution between granular phases $i$ and $j$, and $P_{s,ik}$ is the granular pressure between phases $i$ and $k$. The drag, radial distribution function, and granular pressure are determined by models and will be discussed in Sec. 3.1 and Sec. 4. The specific manner as to how these source terms are solved can be found in Appendix B.7 of Houim and Oran (2016).

The energy transfer term, $\dot{e}_{ij}$, is defined as

$$
\dot{e}_{ij} = \dot{e}_{HT,ij} + \dot{ω}_{i,j} I(e_i, e_j + hf_i − hf_j)
$$

(2.33)

Lastly, the speed of sound for a granular material is given by

$$
c_i^2 = \frac{1}{ρ_i} \left[ \frac{∂P_{tot,i}}{∂α_i} + \frac{2}{3} Θ_i \frac{\left( \frac{∂P_{tot,i}}{∂Θ_i} \right)^2}{ρ_i α_i^2} \right]
$$

(2.34)

where $P_{tot,i} = P_{s,i} + P_{fr,i}$. Because different models can be used for the granular pressure, frictional pressure, and additional models used within radial distribution functions, the specific form this takes is not discussed here.

The topic of granular flows, or kinetic theory, is quite extensive and thus it would be impractical to attempt to provide complete descriptions and derivations of the equations and models discussed here. For more more details on this topic, the reader should consult the following resources:

- For derivations relating to molecular gasses, see Chapman et al. (1990)
- For more practical derivations, see Gidaspow (1994)
- For applications to compressible flows, see Fox (2019)
- For derivations of the polydisperse formulations, see Huilin and Gidaspow (2003) and Chao et al. (2011)
