"""Synthetic evaluation fixtures. Uses the unmodified Graph Editor model/renderer."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import logging
import platform
import subprocess
import sys
import warnings
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties, findfont
from PIL import Image, ImageDraw, ImageFont

from materials_data_studio.tools.graph_document import load_graph_document, save_graph_document
from materials_data_studio.tools.graph_export import GraphicsSettings, save_graphics
from materials_data_studio.tools.graph_fit import quick_fit
from materials_data_studio.tools.graph_render import IgorMatplotlibRenderer
from materials_data_studio.tools.graph_waves import empty_document, make_wave, put_waves, validate_references
from materials_data_studio.tools.pxp_model import (
    PxpAnnotation, PxpAnnotationStyle, PxpAxis, PxpAxisStyle, PxpBoxPlot,
    PxpContour, PxpDrawing, PxpGraph, PxpGraphStyle, PxpImage, PxpLayoutItem,
    PxpTrace, PxpViolinPlot,
)

from materials_data_studio.version import __version__

SEED = 20261117
RNG = np.random.default_rng(SEED)
PALETTE = ['#0072B2', '#D55E00', '#009E73', '#CC79A7', '#E69F00', '#333E50']
OUT = Path.cwd() / '.test-tmp/graph-editor-baselines/exploratory-v1'
WAVES = []
GRAPHS = []
CASES = []
FITS = {}


def rgb(c):
    return tuple(int(c[i:i+2], 16) * 257 for i in (1, 3, 5))


def wave(name, values, unit='', scaling=None, dimunits=None, recipe=''):
    w = make_wave(name, values)
    w = replace(w, data_units=unit, wave_note=f'SYNTHETIC; seed={SEED}; {recipe}')
    if scaling is not None:
        w = replace(w, dimension_scaling=tuple(scaling))
    if dimunits is not None:
        w = replace(w, dimension_units=tuple(dimunits))
    WAVES.append(w)
    return w.igor_path


def trace(name, y, x=None, ci=0, **kw):
    return PxpTrace(name, y, x, color_igor=rgb(PALETTE[ci]), line_width=1.6, **kw)


def annotation(name, text, anchor='LT', x=3, y=3, size=10, **kw):
    return PxpAnnotation(name, text, PxpAnnotationStyle(
        anchor=anchor, x_percent=x, y_percent=y, offset_mode='native',
        font_size=size, frame=0, transparent=True, **kw))


def legend(entries, anchor='LT', x=3, y=4):
    return annotation('legend', '\n'.join(r'\s(' + a + ') ' + b for a, b in entries), anchor, x, y)


def graph(key, traces=(), xlabel='', ylabel='', xlim=None, ylim=None,
          extra_axes=(), annotations=(), font='DejaVu Sans', right=22, **kw):
    st = PxpAxisStyle(font_family=font, font_size=11, tick=2, mirror=1,
        thickness=.85, major_length=4.5, minor_length=2.5, minor_enabled=True,
        axis_color=rgb('#253245'), label_color=rgb('#253245'),
        tick_label_color=rgb('#253245'), tick_count=5)
    style = PxpGraphStyle(width_points=360, height_points=230,
        margins=(('left', 68), ('bottom', 51), ('top', 18), ('right', right)),
        axis_defaults=st, font_family=font, font_size=11,
        plot_background=(65535,)*3, window_size=(450+right-22, 299))
    axes = (PxpAxis('bottom', '\\Z13' + xlabel, xlim), PxpAxis('left', '\\Z13' + ylabel, ylim), *extra_axes)
    result = PxpGraph(key, tuple(traces), axes, style=style,
        annotations=annotations, **kw)
    GRAPHS.append(result)
    return result


def case(key, title, category, focus, recipe):
    CASES.append(dict(id=key, title=title, category=category, focus=focus, recipe=recipe))


def make_suite():
    # 01: line styles and scientific units.
    t = np.linspace(5, 300, 241)
    wt = wave('transport:T', t, 'K', recipe='linspace(5,300,241)')
    ts = []
    for i, (r0, a) in enumerate([(12, .0023), (18, .0017), (25, .0011)]):
        y = r0 + a*t**1.8 + 2.5*np.tanh((t-105)/12) + RNG.normal(0, .14, len(t))
        yref = wave(f'transport:rho_{i}', y, 'µΩ cm', recipe='r0+a*T^1.8+2.5*tanh((T-105)/12)+N(0,.14)')
        ts.append(trace(f'Sample_{i}', yref, wt, i, line_style=i))
    graph('01_lines', ts,
        'Temperature (K)', 'Resistivity (µΩ cm)', (0, 310), (0, 90),
        annotations=(legend([(f'Sample_{i}', f'Sample {chr(65+i)}') for i in range(3)]),))
    case('01_lines', '複数の折れ線・線種', 'XY', '線の識別、単位、凡例、余白', 'ρ=r0+aT^1.8+転移項+微小ノイズ、241点×3群')

    # 02–03: native weighted fit and its exact residuals.
    x = np.linspace(0, 10, 21)
    ey = .18 + .025*x
    y = 1.25 + 2.4*x + RNG.normal(0, ey)
    fit = quick_fit(x, y, 'line', sigma=ey)
    FITS['calibration'] = dict(parameters=fit.parameters, values=fit.values, errors=fit.errors, count=fit.count, rss=fit.rss)
    xr = wave('calibration:x', x, 'mmol L^-1')
    yr = wave('calibration:y', y, 'mV')
    elo = wave('calibration:ey_low', ey, 'mV')
    ehi = wave('calibration:ey_high', 1.35*ey, 'mV')
    ex = wave('calibration:ex', np.full_like(x, .09), 'mmol L^-1')
    fx = wave('calibration:fit_x', fit.x)
    fy = wave('calibration:fit_y', fit.calculated)
    graph('02_xy_errors',
        (trace('fit', fy, fx, 1), trace('measurements', yr, xr, 0, mode=3, marker=8,
            marker_size=2.4, error_low=elo, error_high=ehi, x_error_low=ex, x_error_high=ex,
            error_width=.75, error_cap=2.5)),
        'Concentration (mmol L\\S−1\\M)', 'Voltage (mV)', (-.4, 10.6), (0, 29),
        annotations=(legend([('measurements','Measurements'), ('fit','Weighted line fit')]),
            annotation('fit_values', f'Intercept = {fit.values[0]:.3f} mV\nSlope = {fit.values[1]:.3f} mV L mmol\\S−1\\M', 'RB', 3, 5, 9)))
    case('02_xy_errors', 'XY誤差棒＋重み付き直線fit', 'XY', '非対称誤差棒・キャップと記号の重なり', '21点、Y下側σ・上側1.35σ、X±0.09。fitの重みは下側σを明示使用')
    res = wave('calibration:residual', fit.residual, 'mV')
    zero = wave('calibration:zero', np.zeros_like(x), 'mV')
    graph('03_residuals',
        (trace('zero', zero, xr, 5, line_style=1), trace('residual', res, xr, 0, mode=3, marker=8, marker_size=2.5,
            error_low=elo, error_high=elo)),
        'Concentration (mmol L\\S−1\\M)', 'Residual (mV)', (-.4, 10.6), (-1.2, 1.2))
    case('03_residuals', 'fit残差・ゼロ基準', 'XY', 'ゼロ線・負値・誤差棒の見やすさ', '02のnative Quick Fitが返した実測点ごとの残差')

    # 04: nonlinear peak fitting from the editor's own implementation.
    sx = np.linspace(-5, 5, 121)
    sy = .18 + 2.7*np.exp(-((sx-.6)/1.05)**2) + RNG.normal(0, .055, len(sx))
    gf = quick_fit(sx, sy, 'gauss')
    FITS['gaussian'] = dict(parameters=gf.parameters, values=gf.values, errors=gf.errors, count=gf.count, rss=gf.rss)
    sxx = wave('spectrum:x', sx, 'meV'); syy = wave('spectrum:y', sy, 'a.u.')
    gxx = wave('spectrum:fit_x', gf.x, 'meV'); gyy = wave('spectrum:fit_y', gf.calculated, 'a.u.')
    graph('04_peak_fit',
        (trace('gauss_fit', gyy, gxx, 1), trace('spectrum', syy, sxx, 0, mode=3, marker=8, marker_size=1.8)),
        'Energy (meV)', 'Intensity (a.u.)', (-5, 5), (0, 3.4),
        annotations=(legend([('spectrum','Synthetic observations'),('gauss_fit','Gaussian fit')], 'RT'),))
    case('04_peak_fit', '非線形ピークfit', 'XY', '観測点と滑らかなfit曲線の分離', 'baseline+2.7exp[-((E−0.6)/1.05)^2]+N(0,0.055)、native gauss fit')

    # 05: logarithmic axes spanning six orders.
    lx = np.geomspace(.01, 100, 65); ly = .45*lx**1.45*np.exp(RNG.normal(0,.065,len(lx)))
    lxr = wave('power:x', lx); lyr = wave('power:y', ly); lr = wave('power:reference', .45*lx**1.45)
    g = graph('05_loglog',
        (trace('power_data', lyr, lxr, 0, mode=3, marker=8, marker_size=2), trace('power_ref', lr, lxr, 1, line_style=1)),
        'Frequency (Hz)', 'Response (a.u.)', (.008, 140), (3e-4, 1e3),
        annotations=(legend([('power_data','Synthetic data'),('power_ref','0.45 f\\S1.45\\M')]),))
    GRAPHS[-1] = replace(g, axes=tuple(replace(a,style=replace(a.style,log=1)) for a in g.axes))
    case('05_loglog', '両対数プロット', 'XY', '指数表記・minor tick・広い値域', 'y=0.45x^1.45×対数正規ノイズ、x=0.01〜100')

    # 06: distinct Y-axis colors and units.
    time = np.linspace(0, 60, 181)
    tr = wave('dual:time', time, 'min'); temp = wave('dual:T', 295+45*(1-np.exp(-time/15)), 'K')
    resistance = wave('dual:R', 11+9*(1-np.exp(-time/17))+.12*np.sin(time/2), 'Ω')
    axr = PxpAxis('right', '\\Z13Resistance (Ω)', (9,23), side='right',
        style=PxpAxisStyle(axis_color=rgb(PALETTE[1]),label_color=rgb(PALETTE[1]),tick_label_color=rgb(PALETTE[1]),
            label_position_mode=3,label_position=52))
    g = graph('06_dual_axis',
        (trace('temperature', temp, tr, 0), trace('resistance', resistance, tr, 1, axis='right',line_style=1)),
        'Time (min)', 'Temperature (K)', (0,60), (290,350), extra_axes=(axr,), right=72,
        annotations=(legend([('temperature','Temperature'),('resistance','Resistance')], 'LT'),))
    GRAPHS[-1] = replace(g,axes=tuple(replace(a,style=replace(a.style,axis_color=rgb(PALETTE[0]),
        label_color=rgb(PALETTE[0]),tick_label_color=rgb(PALETTE[0]))) if a.name=='left' else a for a in g.axes))
    case('06_dual_axis', '左右2軸', 'XY', '左右ラベルの余白・軸と線の対応', '指数的な温度安定化と抵抗応答、181点')

    h = np.linspace(-4, 4, 401)
    hr = wave('magnetism:H', h, 'T'); branches=[]
    for i, shift in enumerate([.45,-.45]):
        mr=wave(f'magnetism:M{i}', .92*np.tanh((h-shift)/.38)+.015*h, 'µB f.u.^-1')
        branches.append(trace(f'branch{i}', mr, hr, i, line_style=i))
    graph('07_hysteresis', branches,
        'Magnetic field (T)', 'Moment (µB f.u.\\S−1\\M)', (-4,4), (-1.15,1.15),
        annotations=(legend([('branch0','Increasing field'),('branch1','Decreasing field')], 'LT'),),
        drawings=(PxpDrawing('DrawLine',(-4,0,4,0),xcoord='bottom',ycoord='left',line_style=1,color=rgb('#ADB6C2'),layer='UserBack'),))
    case('07_hysteresis', 'ヒステリシス', 'XY', '負値・原点・近い曲線と線種', 'M=0.92tanh((H∓0.45)/0.38)+0.015H、401点×2')

    xx=np.linspace(15,75,2401); xxr=wave('xrd:angle',xx,'degree'); xtr=[]
    for i in range(3):
        yy=8+RNG.uniform(0,1.5,len(xx))
        for p,a in zip([24.1,31.7,38.2,47.6,56.8,66.1],[25,80,42,65,36,19],strict=True):
            yy += a*np.exp(-.5*((xx-(p+.13*i))/(.16+.025*i))**2)
        rr=wave(f'xrd:pattern{i}',yy,'a.u.')
        xtr.append(trace(f'pattern{i}',rr,xxr,i,offset=(0,105*i)))
    conditions = '\n'.join(
        f'\\K{rgb(PALETTE[i])}\\s(pattern{i}) Annealed at {700+100*i} K'
        for i in (2, 1, 0)
    )
    conditions_legend = annotation('annealing_conditions', conditions, 'RT', 3, 4, 11)
    g=graph('08_stacked_xrd',xtr,
        '2θ (degree)','Intensity / arb. units',(15,75),(0,330),
        annotations=(conditions_legend,))
    GRAPHS[-1]=replace(g,axes=tuple(replace(a,style=replace(a.style,
        **(dict(manual_ticks=(0,10,0,0),manual_minor=(4,0)) if a.name=='bottom'
           else dict(tick_count=0,minor_enabled=False)))) for a in g.axes))
    case('08_stacked_xrd','積み重ね回折パターン','XY','鋭いピーク・offset・密なデータ','6本のGaussianピーク、2401点×3、Y offset=0/105/210')

    cats=wave('bars:labels',np.array(['Control','Route A','Route B','Route C']))
    br=wave('bars:mean',[41.2,55.4,63.8,72.1],'%'); ber=wave('bars:sd',[3.4,4.1,3.7,4.5],'%')
    graph('09_category_bars',
        (trace('yield',br,cats,0,mode=5,error_low=ber,error_high=ber,error_color=rgb('#253245')),),
        'Processing route','Yield (%)',(-.7,3.7),(0,90),
        annotations=(annotation('definition','Bars: mean\nError bars: SD','LT',4,4,9),))
    case('09_category_bars','カテゴリ棒グラフ','分布','カテゴリ文字・ゼロ起点・誤差棒','4群の架空の平均とSD。平均集計値の例')

    raw=RNG.normal(50,8,1200); bins=np.linspace(20,80,31); counts,edges=np.histogram(raw,bins)
    centers=(edges[:-1]+edges[1:])/2
    hx=wave('hist:bin_centers',centers,'nm'); hy=wave('hist:count',counts,'count')
    exx=np.linspace(20,80,301); expected=1200*2/(8*np.sqrt(2*np.pi))*np.exp(-.5*((exx-50)/8)**2)
    hfx=wave('hist:reference_x',exx,'nm'); hfy=wave('hist:reference_count',expected,'count')
    wave('hist:raw',raw,'nm')
    graph('10_histogram',
        (trace('histogram',hy,hx,0,mode=5),trace('normal_reference',hfy,hfx,1,line_style=1)),
        'Diameter (nm)','Count per 2 nm bin',(20,80),(0,140),
        annotations=(legend([('histogram','Observed counts'),('normal_reference','Generating distribution')]),))
    case('10_histogram','ヒストグラム','分布','ビン幅・単位・基準分布との対応','N(50,8)の1200点、2nm幅。線は生成分布の期待度数でfitではない')

    groups=[]
    for i in range(4):
        values=RNG.normal([46,52,58,65][i],[4,6,4.5,7][i],48)
        values=np.r_[values,[values.mean()+18]]
        groups.append(wave(f'distribution:group{i}',values,'MPa'))
    dl=wave('distribution:labels',np.array(['Control','Low dose','Mid dose','High dose']))
    bx=PxpBoxPlot(waves=tuple(groups),box_fill=rgb('#D4EAF5'),box_color=rgb(PALETTE[0]),
        median_color=rgb(PALETTE[1]),whisker_color=rgb(PALETTE[0]),
        show_data='All',show_mean=True,notched=True,whisker_method=(2,),box_width=.5,cap_width=.6,jitter=.7)
    graph('11_boxplot',
        (trace('boxes',groups[0],dl,0,box=bx),), 'Treatment','Strength (MPa)',(-.65,3.65),(25,100))
    case('11_boxplot','箱ひげ＋生データ','分布','四分位・外れ値・jitter・カテゴリ配置','49点×4群、Tukey whisker=1.5IQR内の最遠点、notchと平均を表示')
    vi=PxpViolinPlot(waves=tuple(groups),fill_color=rgb('#DAF1E8'),line_color=rgb(PALETTE[2]),
        show_data=True,show_median=True,show_mean=True,box_width=.17,jitter=.5)
    graph('12_violin',
        (trace('violins',groups[0],dl,2,violin=vi),),'Treatment','Strength (MPa)',(-.65,3.65),(25,100))
    case('12_violin','バイオリン＋生データ','分布','KDE形状・幅・平均中央値・生データ','11と完全に同じ4群。native既定bandwidth/kernelを使用')

    n=95; area=RNG.uniform(2,18,n); porosity=RNG.uniform(0,1,n)
    strength=90-2.2*area-17*porosity+RNG.normal(0,3,n); mass=RNG.uniform(1,7,n)
    ar=wave('channels:area',area,'µm^2'); sr=wave('channels:strength',strength,'MPa')
    pr=wave('channels:porosity',porosity,'fraction'); mr=wave('channels:mass',mass,'mg')
    graph('13_multivariate',
        (trace('particles',sr,ar,0,mode=3,marker=19,z_color=(pr,0,1,'viridis',0,''),
            z_size=(mr,1,7,2,7,''),color_scale=True),),
        'Projected area (µm\\S2\\M)','Strength (MPa)',(0,20),(20,95),right=95,
        annotations=(annotation('encoding','Color = porosity (fraction)\nMarker size = mass (1–7 mg)','LB',3,4,8),))
    case('13_multivariate','点ごとの色・大きさ','XY','カラー凡例・記号サイズ・過密度','95点、色=空隙率0〜1、size=質量1〜7mg。native trace ColorScale')

    gx=np.linspace(-3,3,121); gy=np.linspace(-2,2,101); X,Y=np.meshgrid(gx,gy,indexing='ij')
    field=np.exp(-((X+.9)**2/1.1+(Y-.2)**2/.6))+.72*np.exp(-((X-1.2)**2/.4+(Y+.6)**2/.85))
    field+=.08*np.cos(2*X)*np.cos(3*Y)
    fieldref=wave('maps:field',field,'a.u.',((gx[0],gx[1]-gx[0]),(gy[0],gy[1]-gy[0])),('mm','mm'))
    cb=PxpAnnotationStyle(anchor='LC',x_percent=107,y_percent=0,offset_mode='legacy',
        font_size=10,width=10,height_percent=90,frame=0)
    cba=PxpAxisStyle(font_family='DejaVu Sans',font_size=10)
    graph('14_heatmap',
        xlabel='X position (mm)',ylabel='Y position (mm)',xlim=(-3,3),ylim=(-2,2),right=104,
        images=(PxpImage(fieldref,color_table='viridis',color_range=(-.1,1.15),colorbar_visible=True,
            colorbar_label_raw='Response (a.u.)',colorbar_style=cb,colorbar_axis=cba),))
    case('14_heatmap','2Dヒートマップ','画像','物理座標・カラーバー・画像の向き','2つの2D Gaussian＋弱い周期背景、121×101。配列第0軸=X')
    logmap=.002+np.exp(-((X+.7)**2/.35+(Y-.4)**2/.5))+ .1*np.exp(-((X-1.1)**2/1.8+(Y+.7)**2/.6))
    mask=((X-1.65)**2+(Y-1)**2)<.17; logmap[mask]=np.nan
    logref=wave('maps:log_field',logmap,'a.u.',((gx[0],gx[1]-gx[0]),(gy[0],gy[1]-gy[0])),('mm','mm'))
    graph('15_log_map_nan',
        xlabel='X position (mm)',ylabel='Y position (mm)',xlim=(-3,3),ylim=(-2,2),right=104,
        images=(PxpImage(logref,color_table='magma',color_range=(.002,1.1),log_color=True,
            colorbar_visible=True,colorbar_label_raw='Intensity (a.u.)',colorbar_style=replace(cb,log_axis=True),colorbar_axis=cba),),
        annotations=(annotation('missing_data','No data','MC',27.5,25,9),))
    case('15_log_map_nan','対数画像・NaN','画像','対数色目盛・欠損領域・低強度','正の2ピーク＋0.002背景。円領域をNaNとし透明表示')
    graph('16_contours',
        xlabel='X position (mm)',ylabel='Y position (mm)',xlim=(-3,3),ylim=(-2,2),
        contours=(PxpContour(fieldref,tuple(np.arange(0,1.01,.1)),False,'viridis',False),),
        annotations=(annotation('levels','Levels: 0.0, 0.1, …, 1.0','RT',3,3,9),))
    case('16_contours','線の等高線','画像','レベル間隔・輪郭の連続性','14と同じmatrix、0〜1を0.1刻み。nativeのレベル数値ラベルは未設定')
    graph('17_filled_contours',
        xlabel='X position (mm)',ylabel='Y position (mm)',xlim=(-3,3),ylim=(-2,2),right=104,
        images=(PxpImage(fieldref,color_table='viridis',color_range=(-.1,1.2),colorbar_visible=True,
            colorbar_label_raw='Response (a.u.)',colorbar_style=cb,colorbar_axis=cba),),
        contours=(PxpContour(fieldref,tuple(np.linspace(-.1,1.2,14)),True,'viridis',False),))
    case('17_filled_contours','塗りつぶし等高線','画像','連続画像と離散レベルの違い・境界','14と同じmatrix、−0.1〜1.2の14境界。native Contourの範囲内')

    # Host rectangle uses the editor's point-based page geometry.
    ix=np.linspace(0,12,601); iy=.09+.82*np.exp(-ix/2.6)+.055*np.exp(-((ix-8.2)/.24)**2)
    irx=wave('inset:t',ix,'s'); iry=wave('inset:y',iy,'V')
    host=graph('18_inset',
        (trace('relaxation',iry,irx,0),),'Time (s)','Signal (V)',(0,12),(0,1.02),
        annotations=(legend([('relaxation','Exponential relaxation')]),))
    child=graph('_inset_detail',
        (trace('detail',iry,irx,1),),'t (s)','V',(7.3,9.1),(.10,.19),host=host.name,host_rect=(218,65,431,230))
    child=replace(child,style=replace(child.style,width_points=130,height_points=90,
        margins=(('left',35),('bottom',30),('top',9),('right',8)),font_size=8,
        axis_defaults=replace(child.style.axis_defaults,font_size=8,tick_count=3)),
        axes=tuple(replace(a,label_raw=a.label_raw.replace('\\Z13','\\Z9')) for a in child.axes))
    GRAPHS[-1]=child
    case('18_inset','拡大inset','構成','insetの大きさ・親子の余白・ラベルの縮尺','指数緩和＋8.2秒の小ピーク。1階層のnative Subwindow')

    jt=np.linspace(2,20,91); jcp=2.5*jt+.031*jt**3
    jtr=wave('typography:T',jt,'K'); jyr=wave('typography:Cp',jcp/jt,'mJ mol^-1 K^-2')
    graph('19_typography',
        (trace('heat_capacity',jyr,jtr,0),),'温度 T (K)','C\\Bp\\M/T (mJ mol\\S−1\\M K\\S−2\\M)',(0,21),(0,17),
        font='Noto Sans CJK JP',right=28,
        annotations=(annotation('equation','C\\Bp\\M/T = γ + βT\\S2\\M\nγ = 2.5 mJ mol\\S−1\\M K\\S−2\\M\nβ = 0.031 mJ mol\\S−1\\M K\\S−4\\M','LT',3,4,10),))
    case('19_typography','日本語・科学記号・上下付き','組版','日本語フォント・Greek・上付き下付き・行間','Cp=γT+βT³をCp/T表示。Noto Sans CJK JPを明示指定')

    tt=np.arange(0,48.01,.5)
    epoch=(datetime(2026,11,15,tzinfo=timezone.utc)-datetime(1904,1,1,tzinfo=timezone.utc)).total_seconds()
    seconds=tt*3600+epoch
    vals=21+2.2*np.sin(2*np.pi*(tt-7)/24)+RNG.normal(0,.12,len(tt)); vals[32:39]=np.nan
    dtx=wave('date:time',seconds,'s since 1904-01-01'); dty=wave('date:T',vals,'°C')
    g=graph('20_dates_gaps',
        (trace('sensor',dty,dtx,2),),'Date / time','Temperature (°C)',(seconds[0],seconds[-1]),(17,25),right=75)
    g=replace(g,style=replace(g.style,margins=tuple((k,73 if k=='bottom' else v) for k,v in g.style.margins)))
    GRAPHS[-1]=replace(g,axes=tuple(replace(a,style=replace(a.style,date_info=(0,1,0),tick_count=4,
        manual_ticks=(epoch,43200,0,0),manual_minor=(3,0),font_size=9.5)) if a.name=='bottom' else a for a in g.axes))
    case('20_dates_gaps','日時軸・欠損区間','XY','日時目盛の改行・密度・NaNで線が途切れるか','48時間を30分間隔、正弦波＋ノイズ。7点のNaN区間')

    # Native page layouts are evaluated as their own outputs.
    for key,names in [
        ('21_layout_science',['01_lines','04_peak_fit','07_hysteresis','14_heatmap']),
        ('22_layout_statistics',['09_category_bars','10_histogram','11_boxplot','12_violin'])]:
        rects=[(18,28,304,386),(308,28,594,386),(18,414,304,772),(308,414,594,772)]
        children=[]
        for index,n in enumerate(names):
            src=next(g for g in GRAPHS if g.name==n)
            childname=f'_{key}_panel{index}'
            anns=src.annotations
            if n=='04_peak_fit':
                anns=(legend([('spectrum','Data'),('gauss_fit','Gaussian fit')],'RT'),)
            if n=='07_hysteresis':
                anns=(annotation('branch_key','Solid: H↑  ·  dotted: H↓','LT',3,4,8),)
            style=replace(src.style,width_points=185,height_points=205,
                margins=(('left',52),('bottom',44),('top',14),('right',76 if key.startswith('21') else 12)),font_size=10,
                axis_defaults=replace(src.style.axis_defaults,font_size=10,tick_count=4))
            child=replace(src,name=childname,style=style,annotations=anns,
                axes=tuple(replace(a,label_raw=a.label_raw.replace('\\Z13','\\Z11')) for a in src.axes))
            if child.images:
                child=replace(child,images=tuple(replace(im,colorbar_style=replace(im.colorbar_style,font_size=8,width=7),
                    colorbar_axis=replace(im.colorbar_axis,font_size=8)) for im in child.images))
            GRAPHS.append(child);children.append(childname)
        GRAPHS.append(PxpGraph(key,window_kind='Layout',style=PxpGraphStyle(window_size=(612,792),font_family='DejaVu Sans',font_size=11),
            layout_items=tuple(PxpLayoutItem(n,r) for n,r in zip(children,rects,strict=True))))
        case(key,'科学図の4パネル' if key.startswith('21') else '分布図の4パネル','構成','パネル間の揃い・縮小時の可読性・カラーバーの干渉',
            'Graph Editorのnative Layout。パネル用の寸法と凡例を設定し、単独図と同じデータを配置')
    GRAPHS.append(PxpGraph('23_layout_fit',window_kind='Layout',style=PxpGraphStyle(window_size=(612,792),font_family='DejaVu Sans',font_size=11),
        layout_items=(PxpLayoutItem('02_xy_errors',(40,32,572,433)),PxpLayoutItem('03_residuals',(40,447,572,770)))))
    case('23_layout_fit','fitと残差の縦配置','構成','X範囲の対応・図間の余白・縮小文字','02と03をnative Layoutで縦に配置。X範囲を共通化')


def selected_document(document, name):
    wanted={name}
    while True:
        before=set(wanted)
        for g in document.current.graphs:
            if g.name in wanted:
                wanted.update(i.graph for i in g.layout_items)
            if g.host in wanted:
                wanted.add(g.name)
        if wanted==before:
            break
    graphs=tuple(g for g in document.current.graphs if g.name in wanted)
    refs=set()
    for g in graphs:
        for t in g.traces:
            refs.update(v for v in (t.y_wave,t.x_wave,t.error_low,t.error_high,t.x_error_low,t.x_error_high,t.z_marker) if v)
            if t.z_color: refs.add(t.z_color[0])
            if t.z_size: refs.add(t.z_size[0])
            if t.box or t.violin: refs.update((t.box or t.violin).waves)
        refs.update(i.wave for i in g.images)
        refs.update(c.wave for c in g.contours)
        for a in g.axes:
            if a.style.user_ticks: refs.update(a.style.user_ticks)
    state=document.current.clone(); state.graphs=graphs
    state.waves=tuple(w for w in document.render_source().waves if w.igor_path in refs)
    return replace(document,current=state)


def native_render(document, name, dpi=130):
    renderer=IgorMatplotlibRenderer()
    g=document.graph(name)
    size=(8.5,11) if g.window_kind=='Layout' else renderer.export_size(g)
    fig=Figure(figsize=size,dpi=dpi); FigureCanvasAgg(fig)
    renderer.render(fig,document,name); fig.canvas.draw()
    return fig


def export_suite():
    for directory in ['figures','documents','data','checks','review']:
        (OUT/directory).mkdir(parents=True,exist_ok=True)
    make_suite()
    doc=empty_document(); doc.source=replace(doc.source,basename='synthetic_graph_benchmark.mdsg')
    doc.current=put_waves(doc,WAVES); doc.current.graphs=tuple(GRAPHS)
    validate_references(doc,doc.current)
    save_graph_document(OUT/'documents'/'all_examples.mdsg',doc)
    restored=load_graph_document(OUT/'documents'/'all_examples.mdsg')
    assert restored.current.graphs==doc.current.graphs
    for graph_model in restored.current.graphs:
        assert not {'case_title', 'case_subtitle', 'detail_title'}.intersection(a.name for a in graph_model.annotations), graph_model.name
    assert len(restored.render_source().waves)==len(WAVES)
    for w in WAVES:
        np.testing.assert_array_equal(w.data,restored.render_source().wave(w.igor_path).data)
    np.savez_compressed(OUT/'data'/'all_synthetic_waves.npz',**{w.igor_path.replace(':','__'):w.data for w in WAVES})
    with (OUT/'data'/'wave_catalog.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f); writer.writerow(['path','shape','unit','scaling','file','note'])
        for w in WAVES:
            fname=w.igor_path.replace(':','__')+'.csv'
            values=w.data
            with (OUT/'data'/fname).open('w',newline='',encoding='utf-8-sig') as wf:
                cw=csv.writer(wf)
                if values.ndim==1:
                    cw.writerow(['index','coordinate',w.name])
                    cw.writerows(zip(range(len(values)),w.coordinate(0),values,strict=True))
                else:
                    cw.writerow(['X','Y','value'])
                    cw.writerows((w.coordinate(0)[i],w.coordinate(1)[j],values[i,j]) for i in range(values.shape[0]) for j in range(values.shape[1]))
            writer.writerow([w.igor_path,str(w.shape),w.data_units,str(w.dimension_scaling),fname,w.wave_note])
    records=[]
    font_messages=[]
    class FontLog(logging.Handler):
        def emit(self, record):
            font_messages.append(record.getMessage())
    font_logger=logging.getLogger('matplotlib.font_manager')
    font_logger.handlers=[FontLog()]
    font_logger.propagate=False
    for entry in CASES:
        font_messages.clear()
        name=entry['id']; g=restored.graph(name)
        sd=selected_document(restored,name)
        path=OUT/'documents'/f'{name}.mdsg'; save_graph_document(path,sd)
        rd=load_graph_document(path)
        validate_references(rd,rd.current)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            f1=native_render(sd,name); f2=native_render(rd,name)
            pix1=np.asarray(f1.canvas.buffer_rgba()); pix2=np.asarray(f2.canvas.buffer_rgba())
            same=np.array_equal(pix1,pix2)
            if not same: raise AssertionError(f'Roundtrip changed rendering: {name}')
            report=rd.compatibility(name)
            for ext in ['png','svg','pdf']:
                save_graphics(OUT/'figures'/f'{name}.{ext}',rd,name,
                    GraphicsSettings(format=ext,dpi=220,size_inches=(8.5,11) if g.window_kind=='Layout' else None))
            figbounds=f2.bbox
            clipped=[]; overlaps=[]
            renderer=f2.canvas.get_renderer()
            for ax in f2.axes:
                if not ax.get_visible(): continue
                for axis in (ax.xaxis,ax.yaxis):
                    if not axis.get_visible(): continue
                    low,high=sorted(axis.get_view_interval())
                    eligible=[axis.label]
                    ticktexts=[]
                    for tick in axis.get_major_ticks()+axis.get_minor_ticks():
                        if not low-1e-8 <= tick.get_loc() <= high+1e-8: continue
                        ticktexts.extend(t for t in (tick.label1,tick.label2) if t.get_visible() and t.get_text().strip())
                    eligible.extend(ticktexts)
                    for txt in eligible:
                        if not txt.get_visible() or not txt.get_text().strip(): continue
                        box=txt.get_window_extent(renderer)
                        if box.width>0 and box.height>0 and (box.x0<-.5 or box.y0<-.5 or box.x1>figbounds.x1+.5 or box.y1>figbounds.y1+.5):
                            clipped.append(txt.get_text())
                    if axis.label.get_visible() and axis.label.get_text().strip():
                        labelbox=axis.label.get_window_extent(renderer)
                        for txt in ticktexts:
                            if labelbox.overlaps(txt.get_window_extent(renderer)):
                                overlaps.append(axis.label.get_text()+' / '+txt.get_text())
            record={**entry,'roundtrip_pixel_identical':same,'rendered':report.rendered,'diagnostics':[asdict(d) for d in report.diagnostics],
                'warnings':sorted({str(w.message) for w in caught}),'possible_text_outside_canvas':sorted(set(clipped)),
                'axis_label_tick_overlaps':sorted(set(overlaps)),
                'font_messages':sorted(set(font_messages)),
                'png_size':Image.open(OUT/'figures'/f'{name}.png').size}
            records.append(record)
            f1.clear();f2.clear()
        print(name,report.rendered,'roundtrip=',same,'warnings=',len(record['warnings']),'outside=',len(record['possible_text_outside_canvas']),flush=True)
    env={p:importlib.metadata.version(p) for p in ['materials-data-studio','numpy','scipy','matplotlib','PySide6-Essentials','pandas']}
    meta=dict(seed=SEED,application_version=__version__,graph_titles=False,
        python=platform.python_version(),platform=platform.platform(),
        packages=env,cases=records,fits=FITS,wave_count=len(WAVES),graph_count=len(GRAPHS),
        method='Unmodified Graph Editor semantic model; native Quick Fit; IgorMatplotlibRenderer and save_graphics; no post-processing of individual plots.')
    (OUT/'checks'/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    pdf_builder = Path(__file__).resolve().with_name('build_review_pdf.py')
    if not pdf_builder.is_file():
        pdf_builder = Path(__file__).resolve().parents[2]/'build_review_pdf.py'
    subprocess.run([sys.executable,str(pdf_builder),'--suite','exploratory-v1','--directory',str(OUT)],check=True)
    contact_sheets(records)


def contact_sheets(records):
    fontpath = findfont(FontProperties(family='Noto Sans CJK JP'), fallback_to_default=False)
    font=ImageFont.truetype(fontpath,18)
    for page,start in enumerate(range(0,len(records),8),1):
        page_records = records[start:start+8]
        row_count = (len(page_records)+1)//2
        sheet=Image.new('RGB',(1720,30+430*row_count),'#EDF1F5'); draw=ImageDraw.Draw(sheet)
        for idx,entry in enumerate(page_records):
            row,col=divmod(idx,2); x=25+col*850; y=25+row*430
            draw.rounded_rectangle((x,y,x+825,y+410),12,fill='white')
            im=Image.open(OUT/'figures'/f"{entry['id']}.png").convert('RGB'); im.thumbnail((795,365))
            sheet.paste(im,(x+(825-im.width)//2,y+7))
            draw.text((x+16,y+380),entry['title'],font=font,fill='#253245')
        sheet.save(OUT/'review'/f'contact_sheet_{page}.png')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output: OUT=args.output.resolve()
    export_suite()
