
#!/usr/bin/env python3
"""
RF Link Budget Calculator (Interactive) with optional `pycraf` integration

Features
- FSPL with distance entered in nautical miles (NM) and converted internally to km
- Atmospheric gaseous attenuation:
    - 'approx' (default): quick-look log-log interpolation (mid-latitude, sea-level)
    - 'pycraf': if installed, uses pycraf-based computation (see notes below)
- Simple rain attenuation scaling (quick-look)
- Cable/connector & polarization mismatch losses
- Noise floor and SNR for a given bandwidth and NF

IMPORTANT
- The 'pycraf' code path is optional. If pycraf is not installed, the script falls back to 'approx'.
- For certification-grade work, rely on ITU-R P.676 / P.838 / P.618 / P.452 via pycraf or official tools.

"""

from dataclasses import dataclass, field
from typing import Optional, Literal
import math


@dataclass
class AtmosEnv:
    temperature_C: float = 15.0
    pressure_hPa: float = 1013.25
    rel_humidity_pct: float = 50.0
    altitude_m: float = 0.0
    elevation_deg: float = 2.0

@dataclass
class LinkInputs:
    freq_MHz: float
    dist_nm: float
    tx_power_W: float
    tx_gain_dBi: float
    rx_gain_dBi: float
    bw_Hz: float
    noise_figure_dB: float
    gas_model: Literal['approx','pycraf'] = 'approx'
    atm_gas_override_dB: Optional[float] = None
    rain_rate_mm_per_h: float = 0.0
    eff_rain_len_km: float = 0.0
    cable_loss_tx_dB: float = 0.0
    cable_loss_rx_dB: float = 0.0
    pol_mismatch_dB: float = 0.0
    extra_losses_dB: float = 0.0
    env: AtmosEnv = field(default_factory=AtmosEnv)

@dataclass
class LinkOutputs:
    fspl_dB: float
    gas_loss_dB: float
    rain_loss_dB: float
    total_path_loss_dB: float
    tx_power_dBm: float
    eirp_dBm: float
    received_power_dBm: float
    noise_floor_dBm: float
    snr_dB: float
    notes: str = ""

def fspl_dB(dist_nm: float, freq_MHz: float) -> float:
    dist_km = dist_nm * 1.852
    return 32.44 + 20*math.log10(max(dist_km, 1e-9)) + 20*math.log10(max(freq_MHz, 1e-9))

def gaseous_specific_atten_dB_per_km_approx(freq_GHz: float) -> float:
    anchors = [
        (0.03, 0.0001),
        (0.10, 0.0002),
        (0.147, 0.00025),
        (0.3,  0.0010),
        (1.0,  0.0020),
        (3.0,  0.0050),
        (10.0, 0.0300),
        (20.0, 0.1000),
    ]
    f = max(freq_GHz, 0.03)
    if f <= anchors[0][0]: return anchors[0][1]
    if f >= anchors[-1][0]: return anchors[-1][1]
    for i in range(len(anchors)-1):
        f1, a1 = anchors[i]
        f2, a2 = anchors[i+1]
        if f1 <= f <= f2:
            lf1, la1 = math.log10(f1), math.log10(a1)
            lf2, la2 = math.log10(f2), math.log10(a2)
            lf  = math.log10(f)
            la  = la1 + (la2 - la1) * ((lf - lf1)/(lf2 - lf1))
            return 10**la
    return anchors[-1][1]

def rain_specific_atten_dB_per_km_approx(freq_GHz: float, R_mm_per_h: float) -> float:
    if R_mm_per_h <= 0: return 0.0
    C = 1e-4
    return C * (freq_GHz**1.2) * (R_mm_per_h**1.0)

def noise_floor_dBm(bw_Hz: float, NF_dB: float) -> float:
    return -174.0 + 10.0*math.log10(max(bw_Hz,1.0)) + NF_dB

def gas_loss_total_dB(freq_MHz: float, dist_km: float, model: str, env: AtmosEnv):
    f_GHz = freq_MHz / 1000.0
    if model == 'pycraf':
        try:
            from pycraf import atm  # type: ignore
            T_K = env.temperature_C + 273.15
            P_hPa = env.pressure_hPa
            RH = env.rel_humidity_pct
            if hasattr(atm, 'gas_specific_attenuation'):
                gamma = float(atm.gas_specific_attenuation(f_GHz, P_hPa, T_K, RH))  # dB/km
                return gamma * dist_km, "pycraf gas_specific_attenuation"
            else:
                gamma = gaseous_specific_atten_dB_per_km_approx(f_GHz)
                return gamma * dist_km, "pycraf present; used approx (function not found)"
        except Exception as ex:
            gamma = gaseous_specific_atten_dB_per_km_approx(f_GHz)
            return gamma * dist_km, f"pycraf error -> used approx: {ex}"
    else:
        gamma = gaseous_specific_atten_dB_per_km_approx(f_GHz)
        return gamma * dist_km, "approx"

def compute_link(inputs: LinkInputs) -> LinkOutputs:
    f_MHz = inputs.freq_MHz
    f_GHz = f_MHz / 1000.0
    d_km  = inputs.dist_nm * 1.852

    L_fspl = fspl_dB(inputs.dist_nm, f_MHz)

    if inputs.atm_gas_override_dB is not None:
        L_gas = inputs.atm_gas_override_dB
        gas_note = "override"
    else:
        L_gas, gas_note = gas_loss_total_dB(f_MHz, d_km, inputs.gas_model, inputs.env)

    gamma_rain = rain_specific_atten_dB_per_km_approx(f_GHz, inputs.rain_rate_mm_per_h)
    L_rain = gamma_rain * inputs.eff_rain_len_km

    L_path = L_fspl + L_gas + L_rain

    Ptx_dBm = 10.0*math.log10(max(inputs.tx_power_W * 1000.0, 1e-12))
    EIRP_dBm = Ptx_dBm + inputs.tx_gain_dBi - inputs.cable_loss_tx_dB

    Prx_dBm = (
        Ptx_dBm
        + inputs.tx_gain_dBi
        + inputs.rx_gain_dBi
        - inputs.cable_loss_tx_dB
        - inputs.cable_loss_rx_dB
        - inputs.pol_mismatch_dB
        - L_path
        - inputs.extra_losses_dB
    )

    N_dBm = noise_floor_dBm(inputs.bw_Hz, inputs.noise_figure_dB)
    SNR_dB = Prx_dBm - N_dBm

    note_txt = f"gas_model={inputs.gas_model}; {gas_note}"
    return LinkOutputs(
        fspl_dB=L_fspl,
        gas_loss_dB=L_gas,
        rain_loss_dB=L_rain,
        total_path_loss_dB=L_path,
        tx_power_dBm=Ptx_dBm,
        eirp_dBm=EIRP_dBm,
        received_power_dBm=Prx_dBm,
        noise_floor_dBm=N_dBm,
        snr_dB=SNR_dB,
        notes=note_txt
    )

def _f(prompt: str, default: float=None) -> float:
    while True:
        s = input(f"{prompt}{' ['+str(default)+']' if default is not None else ''}: ").strip()
        if not s and default is not None:
            return float(default)
        try:
            return float(s)
        except ValueError:
            print("Please enter a number.")

def _choose(prompt: str, options: list[str], default: str) -> str:
    opts = "/".join(options)
    while True:
        s = input(f"{prompt} ({opts}) [{default}]: ").strip().lower()
        if not s:
            return default
        if s in options:
            return s
        print(f"Please type one of: {options}")

if __name__ == "__main__":
    print("RF Link Budget Calculator (Interactive) + optional pycraf\n-------------------------------------------------------")
    freq_MHz         = _f("Enter frequency (MHz)")
    dist_nm          = _f("Enter distance (NM)")
    tx_power_W       = _f("Enter transmit power (W)")
    tx_gain_dBi      = _f("Enter transmit antenna gain (dBi)", 0.0)
    rx_gain_dBi      = _f("Enter receive antenna gain (dBi)", 0.0)
    bw_Hz            = _f("Enter noise bandwidth (Hz)")
    noise_figure_dB  = _f("Enter receiver noise figure (dB)", 6.0)
    rain_rate        = _f("Enter rain rate (mm/h, 0 if clear)", 0.0)
    eff_rain_km      = _f("Enter effective rain path (km)", 0.0)
    cable_tx         = _f("Enter TX cable/connector loss (dB)", 0.0)
    cable_rx         = _f("Enter RX cable/connector loss (dB)", 0.0)
    pol_mis          = _f("Enter polarization mismatch (dB)", 0.0)
    extra_losses     = _f("Enter any extra losses (dB)", 0.0)

    gas_model        = _choose("Gas model", ["approx","pycraf"], "approx")

    print("\nEnvironment (pycraf only; press Enter to accept defaults)")
    T_C   = _f("Temperature (°C)", 15.0)
    P_hPa = _f("Pressure (hPa)", 1013.25)
    RH    = _f("Relative humidity (%)", 50.0)
    ALT_m = _f("Altitude (m)", 0.0)
    EL_deg= _f("Elevation angle (deg)", 2.0)

    env = AtmosEnv(temperature_C=T_C, pressure_hPa=P_hPa, rel_humidity_pct=RH, altitude_m=ALT_m, elevation_deg=EL_deg)

    inputs = LinkInputs(
        freq_MHz=freq_MHz,
        dist_nm=dist_nm,
        tx_power_W=tx_power_W,
        tx_gain_dBi=tx_gain_dBi,
        rx_gain_dBi=rx_gain_dBi,
        bw_Hz=bw_Hz,
        noise_figure_dB=noise_figure_dB,
        gas_model=gas_model,
        rain_rate_mm_per_h=rain_rate,
        eff_rain_len_km=eff_rain_km,
        cable_loss_tx_dB=cable_tx,
        cable_loss_rx_dB=cable_rx,
        pol_mismatch_dB=pol_mis,
        extra_losses_dB=extra_losses,
        env=env
    )

    out = compute_link(inputs)

    print("\nResults\n-------")
    print(f"FSPL:               {out.fspl_dB:.3f} dB")
    print(f"Gas loss:           {out.gas_loss_dB:.3f} dB   ({out.notes})")
    print(f"Rain loss:          {out.rain_loss_dB:.3f} dB")
    print(f"Total path loss:    {out.total_path_loss_dB:.3f} dB")
    print(f"Tx power:           {out.tx_power_dBm:.3f} dBm")
    print(f"EIRP:               {out.eirp_dBm:.3f} dBm")
    print(f"Received power:     {out.received_power_dBm:.3f} dBm")
    print(f"Noise floor:        {out.noise_floor_dBm:.3f} dBm")
    print(f"SNR:                {out.snr_dB:.3f} dB")
