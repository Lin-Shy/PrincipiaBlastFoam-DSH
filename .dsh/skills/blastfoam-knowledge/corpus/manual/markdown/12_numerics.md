# 12 Numerics

A collection of numerical methods is provided that are used within the models describe prior, and can also be used for new application and solvers. Many of the methods are only listed and the reader should view the provided references for a more complete description.

## 12.1 Lookup tables

1D, 2D, and 3D lookup tables are provided, all including support for modified data types, runtime selectable interpolation schemes, and the ability to read or construct the necessary data. The name of the given dictionaries and inputs are dictated by the specific models using the tables, "x" and "f" will be used as place holders for these names. If the dictionary named "xCoeffs" is provided "x" is not used to read the given input (i.e. "xMod" is "mod").

When 1D data is read the field can be constructed with 3 methods: directly read, read from a file given a column, or constructed with a spacing.

| Variable | Description |
|---|---|
| file | Name of a file to read from |
| delim | Delimiter used to seperate data (',' by default) |
| xCol | Column of the data (first column by default) |
| x | Data |
| xMod | Modifier (none by default) |
| nX | Number of values |
| minX | Minimum value |
| maxX | Maximum value |
| deltaX | Spacing |

### 12.1.1 Modifiers

Different modifiers can be used to interpolate scalar data in different spaces, and include

- none
- log10
- pow10 ($10^x$)
- ln
- exp

| Variable | Description |
|---|---|
| xMod | Modifier for the data |

### 12.1.2 Interpolation schemes

Several interpolation schemes are provided to give the user control over the method which is used to interpolate data including

- floor
- ceil
- linearClamp
- linearExtrapolated
- quadraticClamp
- quadraticExtrapolted
- cubicClamp
- cubicExtrapolated

Clamp methods limit the interpolation to the minimum and maximum values of the provided table, and extrapolated methods will use the closest values to extrapolate the given data out of bounds. Different methods can be used for all directions, and "interpolationScheme" is used to define the default method.

| Variable | Description |
|---|---|
| xInterpolationScheme | Interpolation scheme (linearClamp by default) (interpolationScheme) |

### 12.1.3 1D lookup tables

Data is looked up given an $x$ value. First and second derivatives have been implemented and a reverse lookup can be used for scalar data (find $f$ given $x$).

### 12.1.4 2D lookup table

Data is looked up given $x$ and $y$ values. The data can be read from a table or from a list. The default delimiter is ",". The table can also be flipped when reading if the input is reversed (y by x) and a check is done on the size when reading. First and second derivatives (pure and mixed) have been implemented and a reverse lookup can be used for scalar data (find $x$ or $y$ given $f$ and $y$ or $x$).

### 12.1.5 3D lookup tables

Data is looked up given $x$, $y$, and $z$ values. The data can be read from a table or a list. The default delimiters are "," for columns and ";" for rows. The table can also be flipped when reading if the input is reversed (z by y by x) and a check is done on the size when reading. First and second derivatives (pure and mixed) have been implemented.

## 12.2 Equations

A simple equation class has been implemented to support many of the numerical methods. The equations take and input and return a result.

Equation: A single scalar input is used to return a single value. This can be used as a univariate or multivariate equation.

Univariate equation: A List of scalar inputs are used to return a single value. This can be used as a multivariate equation.

Multivariate equation: A list of scalar inputs are used to return a list of values.

## 12.3 Root solvers

A collection of root solvers are provided for finding the roots of univariate, scalar equations. Both the $x$ (absolute and relative) and $y$ (absolute only) values are checked for convergence. The available methods are:

Univariate root solvers:

- bisection
- Brent
- falsePoint
- Halley
- NewtonRaphson
- secant
- Steffensen
- step

Multivariate root solvers:

- goodBroyden (Broyden, 1965)
- badBroyden (Kvaalen, 1991)
- NewtonRaphson

| Variable | Description |
|---|---|
| xTolerance(s) | Relative tolerance for the difference in x (1e-6 by default) |
| xAbsTolerance(s) | Absolute tolerance for the difference in x (1e-6 by default) |
| yTolerance(s) | Absolute tolerance for the y value (1e-6 by default) |
| maxSteps | Maximum number of iteration (100 by default) |

## 12.4 Minimization

A collection of minimization methods are providing for finding the minimums of scalar equations. All methods were implemented using Kochenderfer and Wheeler (2019). The available models are

Univariate minimization:

- bisection
- Fibonacci
- goldenRatio
- NewtonRaphson
- quadraticFit
- ShubertPiyavskii
- step

Multivariate minimization:

- gradientDescent
- NelderMead
- particleSwarm

Nelder-Mead options:

| Variable | Description |
|---|---|
| reflectionCoeff | Scale for reflection (1 by default) |
| expansionCoeff | Scale for expansion (2 by default) |
| contractionCoeff | Scale for contraction (0.5 by default) |

Particle Swarm options:

| Variable | Description |
|---|---|
| narticles | Number of particles used (100 by default) |
| cLocal | Velocity weight toward the best local point |
| cGlobal | Velocity weight toward the best global point |
| vWeight | Weight of previous velocity |

General options:

| Variable | Description |
|---|---|
| xTolerance(s) | Absolute convergence tolerance for the independent variables (1e-6 by default) |
| xRelTolerance(s) | Relative convergence tolerance for the independent variables (1e-6 by default) |
| yTolerance(s) | Absolute convergence tolerance for the evaluated function (1e-6 by default) |
| yRelTolerance(s) | Relative convergence tolerance for the evaluated function (1e-6 by default) |
| maxSteps | Maximum number of iteration (100 by default) |
| nSamples | Number of pre-sample intervals (0 by default) |
| normaliseError | Is the relative error checked for convergence (true by default) |
| tau | Line search (and step) reduction coefficient (0.5 by default) |

## 12.5 Integrators

Numerical integrators have been implemented for arbitrary data types (not only scalars).

Univariate integrators (single input) have the ability to use either adaptive integration or a fixed number of intervals. These methods have also been optimised to reduce the number of function evaluations. The available methods are:

Univariate integrators:

- Boole
- Gaussian
- midPoint
- Simpson13
- Simpson38
- trapezoidal

| Variable | Description |
|---|---|
| tolerance | Convergence tolerance (1e-6 by default) |
| adaptive | Is the integration adaptive (true by default) |
| maxSplits | Maximum number splits (10 by default) |
| nIntervals | Number of intervals (10 by default) |

Because of the complexity of integrating an arbitrary number of dimensions, only a small subset of the univariate integrators a have been implemented for multiple inputs. These methods also do not have the same optimisation as seen in the univariate case. The available options are:

Multivariate integrators:

- Gaussian
- midPoint
- trapezoidal

| Variable | Description |
|---|---|
| tolerances | Convergence tolerance (1e-6 by default) |
| adaptive | Is the integration adaptive (true by default) |
| maxSplits | Maximum number splits (5 by default) |
