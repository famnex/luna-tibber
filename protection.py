"""Automatic reserve from the future cost curve; never writes device registers."""


def reserve(values, ceiling, price, eta, wear, capacity, energy, held=False):
    # Marginal value of retaining energy versus using it now. Equal prices keep
    # the configured future household demand; unexpected extra load gets surplus.
    scores=[v+max(0,price-wear)*eta*ceiling*i/(len(values)-1) for i,v in enumerate(values)]
    best=min(scores)
    candidates=[i for i,s in enumerate(scores) if s<=best+1e-7]
    useful=[i for i in candidates if i==0 or values[i]<values[i-1]-1e-7]
    index=max(useful) if useful else min(candidates)
    required=ceiling*index/(len(values)-1)
    # 30 seconds at the supported inverter's 5kW plus 1% SOC quantisation.
    reaction=max(capacity*.01,5/eta*30/3600)
    trigger=min(ceiling,required+reaction)
    release=min(ceiling,required+2*reaction)
    threshold=release if held else trigger
    locked=required>1e-7 and energy<=threshold+1e-7
    return dict(required_kwh=required,reaction_kwh=reaction,trigger_kwh=trigger,
                release_kwh=release,available_kwh=energy,hold=locked,
                surplus_kwh=max(0,energy-trigger))
