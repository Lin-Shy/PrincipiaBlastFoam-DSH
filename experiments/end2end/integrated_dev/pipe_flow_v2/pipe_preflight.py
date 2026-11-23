"""Check forcing orientation in the tridiagonal steady laminar diffusion operator."""
import math


def check_direction(rows, driving_sign):
    """Sufficient sign check for sign-normalized monotone diffusion discretizations.

    Uniform positive driving and a stationary wall imply a nonnegative velocity.
    The test handles either row-sign convention. It does not solve the system.
    """
    if driving_sign not in (-1, 1):
        raise ValueError("driving_sign must be -1 or 1")
    contrary = []
    for i, (_, lower, diagonal, upper, rhs) in enumerate(rows[:-1]):
        scale = math.copysign(1.0, diagonal)
        # Only infer a contradiction on rows with the monotone stencil.
        # A zero source is valid on a separately imposed symmetry boundary.
        if scale*lower <= 0 and scale*upper <= 0 and driving_sign*scale*rhs < 0:
            contrary.append(i)
    if contrary:
        raise ValueError(f"forcing orientation disagrees with the specified pressure drop "
                         f"on {len(contrary)} monotone diffusion rows; first index {contrary[0]}. "
                         "Check the driving term and the sign convention of the assembled operator.")
