#!/usr/bin/env python3
"""Reine Verlustrechnung, keine Annahme über den tatsächlichen Gerätewirkungsgrad."""
import argparse
import math

def calculate(night, day, efficiency, useful_kwh, wear=0):
    if not all(math.isfinite(v) for v in (night, day, efficiency, useful_kwh, wear)):
        raise ValueError('Alle Eingaben müssen endlich sein')
    if not 0 < efficiency <= 1 or useful_kwh < 0 or wear < 0:
        raise ValueError('Wirkungsgrad > 0 bis 1; Energiemenge und Verschleiß >= 0')
    effective = night / efficiency + wear
    return {'effective_ct':effective,'spread_needed_ct':effective-night,
            'saving_ct_per_kwh':day-effective,'saving_eur':(day-effective)*useful_kwh/100,
            'grid_kwh':useful_kwh/efficiency}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--night',type=float,required=True,help='Nachtpreis ct/kWh')
    p.add_argument('--day',type=float,required=True,help='Vermiedener Tagpreis ct/kWh')
    p.add_argument('--efficiency',type=float,required=True,help='AC-AC Gesamtwirkungsgrad, z.B. 0.85')
    p.add_argument('--useful-kwh',type=float,default=1,help='Später tatsächlich genutzte kWh')
    p.add_argument('--wear',type=float,default=0,help='Angenommene Verschleißkosten ct je nutzbarer kWh')
    a=p.parse_args()
    r=calculate(a.night,a.day,a.efficiency,a.useful_kwh,a.wear)
    print(f"Effektiver Speicherstrompreis: {r['effective_ct']:.2f} ct/kWh")
    print(f"Benötigter Unterschied gegenüber Nachtpreis: > {r['spread_needed_ct']:.2f} ct/kWh")
    print(f"Ersparnis je nutzbarer kWh: {r['saving_ct_per_kwh']:.2f} ct")
    print(f"Ersparnis für {a.useful_kwh:g} nutzbare kWh: {r['saving_eur']:.2f} EUR")
    print(f"Dafür benötigter Netzbezug: {r['grid_kwh']:.2f} kWh")
    print('Annahmen, keine Messwerte. Solarverdrängung und Verbrauchszeitpunkt separat berücksichtigen.')
if __name__=='__main__': main()
