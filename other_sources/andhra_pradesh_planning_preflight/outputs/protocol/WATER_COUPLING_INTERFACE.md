# Frozen data-center water-coupling interface

Future variables are

```text
z[l,k,s]     installed capacity at region l, cooling technology k, source s
a[l,k,s,t]   served energy
```

The groundwater withdrawal interface is

```text
q_dc[n,t] = sum_(l,k,s) M_GW[n,l] * theta_gw[l,k,s]
             * rho[l,k,t] * a[l,k,s,t].
```

`theta_gw` is a documented source share, not a fitting convenience; it may not
be assumed when source accounting is absent. `rho` is a source-resolved water
intensity with explicit facility/campus and withdrawal/consumption boundary.
Groundwater, reclaimed wastewater, desalinated seawater, and other
surface/municipal supply remain distinct. `APPROXIMATE` and `UNRESOLVED`
site-to-groundwater mappings are excluded from the primary optimization set.

This interface is frozen, but no values were invented and no planning problem
was solved.
