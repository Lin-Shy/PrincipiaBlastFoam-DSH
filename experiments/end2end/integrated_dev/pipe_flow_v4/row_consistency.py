"""Test interior row consistency on coordinate polynomials without solving the system."""
import math
from pipe_preflight import check_direction


def inspect_rows(rows, viscosity, pressure_drop):
    if not (math.isfinite(pressure_drop) and pressure_drop>0 and math.isfinite(viscosity) and viscosity>0):
        raise ValueError("Expected positive finite viscosity and pressure drop")
    check_direction(rows,driving_sign=1)
    largest=0.0
    for i in range(1,len(rows)-1):
        r,lower,diag,upper,rhs=rows[i]
        scale=abs(lower)+abs(diag)+abs(upper)
        if abs(lower+diag+upper)>1e-8*scale:
            raise ValueError(f"Interior row {i} does not annihilate a constant. Check diffusion flux balance.")
        # Shift by r_i^2 to avoid cancellation. Row scaling cancels in the ratio.
        moment=lower*(rows[i-1][0]**2-r*r)+upper*(rows[i+1][0]**2-r*r)
        if moment==0:
            raise ValueError(f"No quadratic diffusion response at interior row {i}")
        inferred=-4*viscosity*rhs/moment
        relative=abs(inferred/pressure_drop-1)
        largest=max(largest,relative)
        if relative>.02:
            raise ValueError(f"Interior row {i} implies a signed pressure drop of {inferred:.7g} Pa/m; "
                             f"the declared drop is {pressure_drop:g} Pa/m. Check the length factors when converting "
                             "the integrated source and face fluxes to one common row normalization; scale both sides together.")
    return largest
