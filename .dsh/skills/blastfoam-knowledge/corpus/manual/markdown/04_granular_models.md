# Granular models

For granular phases, additional models are required to account for particle-particle collisions in both the kinetic and frictional regimes. These models include radial distribution, viscosity, conductivity, granular pressure, frictional pressure, solid-solid drag, and packing models.

Some common variables used in the granular models will now be defined. Here, $P_k$ is the summation over all granular phase indices and $α_s$ is the sum of all granular phase volume fractions. The strain is defined as

$$
S = \frac{1}{2}\left[(∇u)^{⊺} + ∇u\right] - \frac{1}{3}(∇·u)I
$$
(4.1)

The symmetric strain is defined as

$$
D = \frac{1}{2}\left[(∇u)^{⊺} + ∇u\right]
$$
(4.2)

Finally, the total granular drag on a phase is defined as

$$
K_{D,i} = \sum_k K_{D,ik}
$$
(4.3)

## 4.1 Radial distribution models

The radial distribution gives the likelihood of a collision between two particles. This is defined between like and unlike particle phases.

### 4.1.1 CarnahanStarling

The Carnahan Starling radial distribution function is only valid for monodisperse flows and is defined as

$$
g_{0,ii} = \frac{1}{1-α_i} + \frac{3α_i}{2(1-α_i)^2} + \frac{α_i^2}{2(1-α_i)^3}
$$
(4.4)

### 4.1.2 SinclairJackson

The radial distribution of Sinclair and Jackson (1989) function is only valid for monodisperse flows and is defined as

$$
g_{0,ii} = \frac{1}{1-\left(\frac{α_i}{α_{i,max}}\right)^{1/3}}
$$
(4.5)

### 4.1.3 LunSavage

The radial distribution function of Lun et al. (1984) is only valid for monodisperse flows and is defined as

$$
g_{0,ii} = \left(1-\frac{α_i}{α_{max,i}}\right)^{-2.5α_{max,i}}
$$
(4.6)

### 4.1.4 Gao

The radial distribution function of Gao et al. (2008) is a modified version of the Sinclair Jackson radial distribution function and is valid for polydisperse flows. It is defined as

$$
g_{0,ij} = \frac{d_i g_{0,i} + d_j g_{0,j}}{d_i + d_j}
$$
(4.7)

$$
g_{0,i} = \frac{1}{1-\left(\frac{α_i}{α_{i,max}}\right)^{1/3}}
$$
(4.8)

### 4.1.5 Lebowitz

The Lebowitz radial distribution function (Benyahia et al., 2012) is valid for polydisperse flows and is defined as

$$
g_{0,ij} = \frac{1}{1-α_s} + \frac{3d_i d_j}{(1-α_s)^2(d_i+d_j)}\sum_k\frac{α_k}{d_k}
$$
(4.9)

## 4.2 Granular viscosity models

The modeling of granular viscosity is used to determine the stress seen in a granular phase. These models only account for single collisions (frictional models will have additional contributions for multiple collisions).

### 4.2.1 Gidaspow

The Gidaspow viscosity model (Gidaspow, 1994) is for monodisperse flows and is defined as

$$
ν_{s,i} = \frac{4}{5}α_i^2 g_{0,ii}\frac{(1+e_{ij})}{π} + \frac{1}{15}\sqrt{π}g_{0,ii}(1+e_{ii})α_i^2 + \frac{1}{6}\sqrt{π}α_i + \frac{10}{96}\sqrt{π}(1+e_{ii})g_{0,ii}
$$
(4.10)

### 4.2.2 HrenyaSinclair

The Hrenya Sinclair viscosity model (Hrenya and Sinclair, 1997) is for monodisperse flows and is defined as

$$
ν_{s,i} = \frac{4}{5}α_i^2 g_{0,ii}\frac{(1+e_{ij})}{π} + \frac{1}{15}\sqrt{π}g_{0,ii}(3e_{ii}-1)\frac{α_i^2}{3-e_{ii}} + \frac{1}{6}\frac{\sqrt{π}α_i(0.5λ+0.25(3e_{ii}-1))}{0.5(3-e_{ii})λ} + \frac{10}{96}\frac{\sqrt{π}}{(1+e_{ii})0.5(3-e_{ii})g_{0,ii}λ}
$$
(4.11)

where

$$
λ = 1 + \frac{d_i L}{6\sqrt{2α_i}}
$$
(4.12)

| Variable | Description |
|---|---|
| L | characteristic length [m] |

### 4.2.3 Princeton

The Princeton viscosity model (Agrawal et al., 2001) is for polydisperse flows and is defined as

$$
ν_{s,i} = ρ_i\frac{3.6}{3}\left[\frac{µ_i^*}{g_{0,ii}η(2-η)}\left(1+\frac{8}{5}η\sum_k(α_k g_{0,ik})\right)\times\left(1+\frac{8}{5}η(3η-2)\sum_k(α_k g_{0,ik})\right)+\frac{3}{5}ηµ_b\right]
$$
(4.13)

where

$$
µ_i^* = \frac{ρ_iα_i g_{0,ii}Θ_i µ}{ρ_i\sum_k(α_k g_{0,ik})Θ_i + \frac{2K_{d,i}µ}{ρ_iα_i}}
$$
(4.14)

$$
µ = \frac{5}{96}ρ_i d_i\sqrt{πΘ_i}
$$
(4.15)

and

$$
µ_b = \frac{256}{5π}µα_i\sum_k(α_k g_{0,ik})
$$
(4.16)

### 4.2.4 Syamlal

The Syamlal viscosity model (Syamlal et al., 1993) is for monodisperse flows and is defined as

$$
ν_{s,i} = \frac{4}{5}α_i^2 g_{0,ii}\frac{(1+e_{ii})}{π} + \frac{1}{15}\sqrt{π}g_{0,ii}(3e_{ii}-1)\frac{α_i^2}{3-e_{ii}} + \frac{1}{6}\frac{\sqrt{π}α_i}{3-e_{ii}}
$$
(4.17)

### 4.2.5 none

No granular viscosity is used. This also removes the conductivity contribution to the granular energy equation.

## 4.3 Granular conductivity models

### 4.3.1 Chao

The Chao granular conductivity model Chao et al. (2011) is defined as

$$
κ_{s,i} = \frac{2κ_{dilute,i}}{\frac{1}{N}\sum_k(1+e_{ik})g_{0,ik}}\left[1+\frac{6}{5}\sum_kα_k(1+e_{ik})g_{0,ik}\right]^2
$$
(4.18)

where N is the number of granular phases and

$$
κ_{dilute,i} = \frac{15ρ_iΘ_i}{\sum_k\left(\frac{π}{\sqrt{2π}n_k d_{ij}^2(\sqrt{Θ_i}+\sqrt{Θ_j}-0.56\sqrt[4]{Θ_iΘ_j})}\right)}
$$
(4.19)

### 4.3.2 Gidaspow

The Gidaspow conductivity model (Gidaspow, 1994) is for monodisperse flows and is defined as

$$
κ_{s,i} = \frac{2α_i^2 g_{0,ii}(1+e_{ii})}{\sqrt{π}} + \frac{9}{8}\sqrt{π}g_{0,ii}0.5(1+e_{ii})α_i^2 + \frac{15}{16}\sqrt{π}α_i + \frac{25}{64}\sqrt{π}g_{0,ii}(1+e_{ii})
$$
(4.20)

### 4.3.3 HrenyaSinclair

The Hrenya Sinclair conductivity model (Hrenya and Sinclair, 1997) is for monodisperse flows and is defined as

$$
κ_{s,i} = \frac{2α_i^2 g_{0,ii}(1+e_{ii})}{\sqrt{π}} + \frac{9}{8}\frac{\sqrt{π}g_{0,ii}0.25(1+e_{ii})^2(2e_{ii}-1)α_i^2}{\frac{49}{16}-\frac{33}{16}e_{ii}} + \frac{15}{16}\frac{\sqrt{π}α_i(0.5e_{ii}^2+0.25e_{ii}-0.75+λ)}{(\frac{49}{16}-\frac{33}{16}e_{ii})λ} + \frac{25}{64}\frac{\sqrt{π}g_{0,ii}λ(1+e_{ii})}{\frac{49}{16}-\frac{33}{16}e_{ii}}
$$
(4.21)

where

$$
λ = 1 + \frac{d_i L}{6\sqrt{2α_i}}
$$
(4.22)

| Variable | Description |
|---|---|
| L | characteristic length [m] |

### 4.3.4 Princeton

The Princeton conductivity model (Agrawal et al., 2001) is for polydisperse flows and is defined as

$$
κ_{s,i} = \frac{κ_i^*}{g_{0,ii}}\left[\left(1+\frac{12}{5}η\sum_k(α_k g_{0,ik})\right)\left(1+\frac{12}{5}η^2(4η-3)\sum_k(α_k g_{0,ik})\right)+\frac{64}{25π}(41-33η)η^2\left(\sum_k(α_k g_{0,ik})\right)^2\right]
$$
(4.23)

where

$$
κ_i^* = \frac{ρ_iα_i g_{0,ii}Θ_i κ_i}{ρ_i\sum_k(α_k g_{0,ik})Θ_i + \frac{6K_{d,i}κ_i}{5ρ_iα_i}}
$$
(4.24)

and

$$
κ_i = \frac{75ρ_i d_i\sqrt{πΘ_i}}{48η(41-33η)}
$$
(4.25)

### 4.3.5 Syamlal

The Syamlal conductivity model (Syamlal et al., 1993) is for monodisperse flows and is defined as

$$
κ_{s,i} = \frac{2α_i^2 g_{0,ii}(1+e_{ii})}{\sqrt{π}} + \frac{9}{8}\frac{\sqrt{π}g_{0,ii}0.25(1+e_{ii})(2e_{ii}-1)α_i^2}{\frac{49}{16}-\frac{33}{16}e_{ii}} + \frac{15}{16}\frac{\sqrt{π}α_i}{\frac{49}{16}-\frac{33}{16}e_{ii}}
$$
(4.26)

## 4.4 Granular pressure models

The granular pressure model is used to calculate the pressure due to single collisions between particles. Pressures that occur due to multiple collisions will be added using the frictional models.

### 4.4.1 Huilin

The Huilin granular pressure model (Huilin and Gidaspow, 2003) is for polydisperse flows and is defined as

$$
P_{s,ij} = \frac{π(1+e_{ij})d_{ij}^3 g_{0,ij}n_i n_j m_i m_j m_0 Θ_i Θ_j}{3(m_i^2 Θ_i + m_j^2 Θ_j)}\times\left[\frac{m_0^2 Θ_i Θ_j}{(m_i^2 Θ_i + m_j^2 Θ_j)(Θ_i+Θ_j)}\right]^{3/2}\times(1-3ω+6ω^2-10ω^3)
$$
(4.27)

with

$$
ω = \frac{m_i Θ_i - m_j Θ_j}{\left[(m_i^2 Θ_i^2 + m_j^2 Θ_j^2)+Θ_i Θ_j(m_i^2+m_j^2)\right]^{1/2}}
$$
(4.28)

### 4.4.2 Lun

The Lun granular pressure model (Lun et al., 1984) is for monodisperse flows and is defined as

$$
P_{s,ij} = α_i α_j ρ_i Θ_i 2(1+e_{ij})g_{0,ij}
$$
(4.29)

## 4.5 Frictional stress models

The frictional stress model acts as a simple way to account for non-singular collisions between particles and results in very large stress when the granular phases approach their packing limit. This results in both a modeled pressure and viscosity to calculate a stress, and limits the ability of particles to move between computational cells. The frictional pressure and viscosity denoted $P_{fr}$ and $ν_{fr}$ act on all granular phases since the packing of particles is dependent on the total volume fraction of particles.

### 4.5.1 JohnsonJackson

The Johnson-Jackson frictional stress model (OpenCFD Ltd., 2018b) uses a smooth function to calculate the pressure

$$
P_{fr} = \begin{cases}\frac{F_r(α_s-α_{crit,s})^{η}}{(α_{max,s}-α_s)^{p}} & \text{if } α_s > α_{crit,s}\\0 & \text{else}\end{cases}
$$
(4.30)

and the frictional viscosity is

$$
ν_{fr} = 0.5P_{fr}\sin(φ)
$$
(4.31)

where φ is the angle of internal friction, and $F_r$, η, and p are model coefficients generally taking values of 0.05, 2, and 5 respectively. $α_{crit,s}$ is the granular particle fraction that the frictional pressure "turns on", and $α_{max,s}$ is the maximum packing limit of all granular phases. Generally $α_{crit,s}$ is taken to be around 0.5.

| Variable | Description |
|---|---|
| Fr | Model coefficient [ ] |
| eta | Model coefficient [ ] |
| p | Model coefficient [ ] |
| phi | Model coefficient [ ] |
| alphaDeltaMin | Minimum value of $α_s - α_{max,s}$ [ ] |
| alphaMinFriction | Volume fraction friction is "turned on" [ ] |

### 4.5.2 Schaeffer

The Schaeffer frictional stress model (Syamlal et al., 1993) uses a power law and the local stress is used to calculate the frictional viscosity. The critical volume fraction, $α_{crit,s}$ should be a value close to that of the packing limit. Because the local packing limit can vary in space when polydispersity is present, the ratio of the local volume fraction by the critical volume fraction is used, i.e. $α_{crit,s} = \left(\frac{α_{crit,s}}{α_{max,s}}\right)_{crit}α_{max,s}$ where $\left(\frac{α_{crit,s}}{α_{max,s}}\right)_{crit}$ is specified by the user and $α_{max,s}$ is the calculated local packing limit. The pressure is defined as

$$
P_{fr} = \begin{cases}1024(α_s-α_{crit,s})^{10} & \text{if } α_s > α_{crit,s}\\0 & \text{else}\end{cases}
$$
(4.32)

and the viscosity is

$$
ν_{fr} = \begin{cases}\frac{0.5P_{fr}\sin(φ)}{\sqrt{\frac{1}{3}(I_1(D)^2-I_2(D))}} & \text{if } α_s > α_{crit,s}\\0 & \text{else}\end{cases}
$$
(4.33)

where $I_1(D)$ is the first invariant (or trace) and $I_2(D)$ is the second invariant.

| Variable | Description |
|---|---|
| phi | Model coefficient [ ] |
| alphaMinFrictionByAlphap | Volume fraction ratio friction is "turned on" [ ] |

### 4.5.3 JohnsonJacksonSchaeffer

For the Johnson Jackson-Schaeffer frictional stress model (OpenCFD Ltd., 2018b), the frictional pressure of Johnson Jackson is used while the viscosity of the Schaeffer model is used.

$$
P_{fr} = \begin{cases}\frac{F_r(α_s-α_{crit,s})^{η}}{(α_{max,s}-α_s)^{p}} & \text{if } α_s > α_{crit,s}\\0 & \text{else}\end{cases}
$$
(4.34)

$$
ν_{fr} = \begin{cases}\frac{0.5P_{fr}\sin(φ)}{\sqrt{\frac{1}{3}(I_1(D)^2-I_2(D))}} & \text{if } α_s > α_{crit,s}\\0 & \text{else}\end{cases}
$$
(4.35)

| Variable | Description |
|---|---|
| Fr | Model coefficient [ ] |
| eta | Model coefficient [ ] |
| p | Model coefficient [ ] |
| phi | Model coefficient [ ] |
| alphaDeltaMin | Minimum value of $α_s - α_{max,s}$ [ ] |
| alphaMinFriction | Volume fraction friction is "turned on" [ ] |

### 4.5.4 Princeton

The Princeton model Agrawal et al. (2001) uses a blending of the Johnson Jackson model when the local volume fraction is greater than $α_{crit,JJ,s}$ but less than $α_{crit,Sc,s}$. As with the Schaeffer model, the critical ratio of $\left(\frac{α_{crit,Sc,s}}{α_{max,s}}\right)_{crit}$ is used as an input rather than $α_{crit,Sc,s}$.

$$
P_{fr} = \begin{cases}1024(α_s-α_{crit,Sc,s})^{10} & \text{if } α_s > α_{crit,Sc,s}\\\frac{F_r(α_s-α_{crit,JJ,s})^{η}}{(α_{max,s}-α_s)^{p}} & \text{if } α_{crit,Sc,s} ≤ α_s > α_{crit,JJ,s}\\0 & \text{else}\end{cases}
$$
(4.36)

The frictional viscosity is defined using

$$
\frac{P_{c,k}}{P_{fr}} = \left[1-\left(\frac{∇·u_s}{n\sqrt{2}\sin(φ)\sqrt{S:S+Θ_k/d_k^2}}\right)^{n-1}\right]
$$
(4.37)

$$
ν_{fr,k} = \frac{\sqrt{2}P_{c,k}\sin(φ)}{\sqrt{S:S+Θ_k/d_k^2}}\left[n-(n-1)\left(\frac{P_{c,k}}{P_{fr}}\right)^{\frac{1}{1-n}}\right]\frac{α_k}{α_s}
$$
(4.38)

and

$$
n = \begin{cases}\frac{\sqrt{3}}{2\sin(φ)} & \text{if } ∇·u_s ≥ 0\\1.03 & \text{else}\end{cases}
$$
(4.39)

| Variable | Description |
|---|---|
| Fr | Model coefficient [ ] |
| eta | Model coefficient [ ] |
| p | Model coefficient [ ] |
| phi | Model coefficient [ ] |
| alphaDeltaMin | Minimum value of $α_s - α_{max,s}$ [ ] |
| alphaMinFriction | Volume fraction friction is "turned on" [ ] |
| alphaMinFrictionByAlphap | Volume fraction ratio friction is "turned on" [ ] |

## 4.6 Packing limit models

The modeling of the packing limit is important in polydisperse flows due to the fact that, when large variations in particle diameters exist locally, the packing limit can vary widely. This is due to the fact that smaller particles can be found in between larger particles, increasing the maximum allowable volume fraction. For monodisperse flows, this is not the case and a constant value packing limit should be used.

### 4.6.1 constant

A constant value for the packing limit is used.

| Variable | Description |
|---|---|
| alphaMax | Packing limit [ ] |

### 4.6.2 YuStandish

The Yu Standish packing model (Yu and Standish, 1987) assumes that the particle phases are ordered from smallest diameter to largest for the calculation of the packing limit. The packing limit is defined as

$$
α_{max,s} = \min_{i∈1:N}\left[\frac{α_{max,i}}{1-\sum_{k=1}^{i-1}\left(1-\frac{α_{max,i}}{p_{ik}}\right)\frac{cx_i}{X_{ik}}-\sum_{k=i+1}^{N}\left(1-\frac{α_{max,i}}{p_{ik}}\right)\frac{cx_i}{X_{ik}}}\right]
$$
(4.40)

where

$$
cx_i = \frac{α_i}{α_s}
$$
(4.41)

$$
X_{ik} = \begin{cases}\frac{1-r_{ik}^2}{2-α_{max,i}} & \text{if } k < i\\1-\frac{1-r_{ik}^2}{2-α_{max,i}} & \text{if } k ≥ i\end{cases}
$$
(4.42)

$$
p_{ik} = \begin{cases}α_{max,i}+α_{max,i}(1-α_{max,i})\times(1-2.35r_{ik}+1.35r_{ik}^2) & \text{if } r_{ik} ≤ 0.741\\α_{max,i} & \text{if } r_{ik} > 0.741\end{cases}
$$
(4.43)

and

$$
r_{ik} = \begin{cases}\frac{d_i}{d_k} & \text{if } i ≥ k\\\frac{d_k}{d_i} & \text{if } i < k\end{cases}
$$
(4.44)

| Variable | Description |
|---|---|
| residualAlpha | Minimum volume fraction to divide by [ ] |

### 4.6.3 FedorsLandel

The Fedors-Landel packing model (Fedors and Landel, 1979) is only valid of for a binary mixture and is defined as

$$
α_{max,s} = \begin{cases}\left[(α_{max,1}-α_{max,2})+(1-\sqrt{r_{21}}(1-α_{max,1})α_{max,2})\right]\times\left[α_{max,1}+(1-α_{max,1})α_{max,2}\right]\frac{cx_i}{α_{max,1}}+α_{max,2} & \text{if } cx_1 ≤ \frac{α_{max,1}}{α_{max,1}+(1-α_{max,1})α_{max,2}}\\\left(1-\sqrt{r_{21}}\right)\left[α_{max,1}+(1-α_{max,1})α_{max,2}\right]cx_2+α_{max,1} & \text{else}\end{cases}
$$
(4.45)

Where the definitions of $r_{21}$ and $cx_i$ are used from the previous section.

| Variable | Description |
|---|---|
| residualAlpha | Minimum volume fraction to divide by [ ] |

## 4.7 Granular drag models

The drag force between granular phases is different than standard drags models due to the fact the the collisions which are a function of the granular energy strongly effect the rate at which the velocities relax. These granular drag models are only necessary when multiple granular phases are used.

### 4.7.1 Chao

The Chao granular drag model (Chao et al., 2011) defines the drag coefficient between phases as

$$
K_{D,ij} = \frac{α_iα_jρ_iρ_j}{m_0 d_{ij}(1+e_{ij})g_{0,ij}}\times\left[\sqrt{2π}(\sqrt{Θ_i}+\sqrt{Θ_j})-\sqrt{2}(Θ_iΘ_j)^{1/4}+0.5π|u_i-u_j|-1.135\sqrt{|u_i-u_j|}\left(\sqrt[4]{4Θ_i}+\sqrt[4]{Θ_j}-0.8\sqrt[8]{Θ_iΘ_j}\right)\right]
$$
(4.46)

### 4.7.2 Syamlal

The Syamlal granular drag model (Benyahia et al., 2012) defines the drag coefficient between phases as

$$
K_{D,ij} = \frac{3(1+e_{ij})\left(\frac{π}{2}+\frac{C_{f,ij}π^2}{8}\right)α_iα_jρ_iρ_j(d_i+d_j)^2 g_{0,ij}|u_i-u_j|}{2π(ρ_i d_i^2+ρ_j d_j^3)}+C_1 P_{fr}
$$
(4.47)

where $C_{f,ij}$ is the coefficient of friction between granular phases i and j, and $C_1$ is the coefficient of frictional pressure.

| Variable | Description |
|---|---|
| C1 | Coefficient of frictional pressure (default is 0) [s/m$^2$] |
