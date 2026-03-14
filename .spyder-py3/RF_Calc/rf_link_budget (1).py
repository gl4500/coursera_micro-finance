
#!/usr/bin/env python3
"""
RF Link Budget Calculator (Interactive)

- FSPL
- Approximate gaseous loss (oxygen + water vapor) via anchor-point interpolation
- Simple rain attenuation scaling
- Cable/connector & polarization mismatch losses
- Noise floor and SNR for a given bandwidth and NF

For certification-grade studies, use ITU-R P.676 / P.838 / P.618 / P.452 models.
"""

from dataclasses import dataclass
from typing import Optional
import math

@dataclass
class LinkInputs:
    freq_MHz: float
    dist_nm: float
    tx_power_W: float
    tx_gain_dBi: float
    rx_gain_dBi: float
    bw_Hz: float
    noise_figure_dB: float
    atm_gas_override_dB: Optional[float] = None
    rain_rate_mm_per_h: float = 0.0
    eff_rain_len_km: float = 0.0
    cable_loss_tx_dB: float = 0.0
    cable_loss_rx_dB: float = 0.0
    pol_mismatch_dB: float = 0.0
    extra_losses_dB: float = 0.0

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

def fspl_dB(dist_km: float, freq_MHz: float) -> float:
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
    C = 1e-4  # quick-look scaling
    return C * (freq_GHz**1.2) * (R_mm_per_h**1.0)

def noise_floor_dBm(bw_Hz: float, NF_dB: float) -> float:
    return -174.0 + 10.0*math.log10(max(bw_Hz,1.0)) + NF_dB

def compute_link(inputs: LinkInputs) -> LinkOutputs:
    f_MHz = inputs.freq_MHz
    f_GHz = f_MHz / 1000.0
    d_km  = inputs.dist_nm * 1.852

    L_fspl = fspl_dB(d_km, f_MHz)
    if inputs.atm_gas_override_dB is not None:
        L_gas = inputs.atm_gas_override_dB
    else:
        gamma_gas = gaseous_specific_atten_dB_per_km_approx(f_GHz)
        L_gas = gamma_gas * d_km

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

    return LinkOutputs(
        fspl_dB=L_fspl,
        gas_loss_dB=L_gas,
        rain_loss_dB=L_rain,
        total_path_loss_dB=L_path,
        tx_power_dBm=Ptx_dBm,
        eirp_dBm=EIRP_dBm,
        received_power_dBm=Prx_dBm,
        noise_floor_dBm=N_dBm,
        snr_dB=SNR_dB
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

if __name__ == "__main__":
    print("RF Link Budget Calculator (Interactive)\n--------------------------------------")
    freq_MHz         = _f("Enter frequency (MHz)")
    dist_nm          = _f("Enter distance (nm)")
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

    inputs = LinkInputs(
        freq_MHz=freq_MHz,
        dist_nm=dist_nm,
        tx_power_W=tx_power_W,
        tx_gain_dBi=tx_gain_dBi,
        rx_gain_dBi=rx_gain_dBi,
        bw_Hz=bw_Hz,
        noise_figure_dB=noise_figure_dB,
        rain_rate_mm_per_h=rain_rate,
        eff_rain_len_km=eff_rain_km,
        cable_loss_tx_dB=cable_tx,
        cable_loss_rx_dB=cable_rx,
        pol_mismatch_dB=pol_mis,
        extra_losses_dB=extra_losses
    )

    out = compute_link(inputs)

    print("\nResults\n-------")
    print(f"FSPL:               {out.fspl_dB:.3f} dB")
    print(f"Gas loss:           {out.gas_loss_dB:.3f} dB")
    print(f"Rain loss:          {out.rain_loss_dB:.3f} dB")
    print(f"Total path loss:    {out.total_path_loss_dB:.3f} dB")
    print(f"Tx power:           {out.tx_power_dBm:.3f} dBm")
    print(f"EIRP:               {out.eirp_dBm:.3f} dBm")
    print(f"Received power:     {out.received_power_dBm:.3f} dBm")
    print(f"Noise floor:        {out.noise_floor_dBm:.3f} dBm")
    print(f"SNR:                {out.snr_dB:.3f} dB")
