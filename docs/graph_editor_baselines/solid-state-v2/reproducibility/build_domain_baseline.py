"""Reproducible solid-state drawing tasks for future MCP/skills evaluation.

Graph mutation goes through the current CommandEngine. No application changes.
Prepared model curves are inputs, never presented as newly fitted measurements.
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import importlib.metadata
import json
import logging
import platform
import shutil
import subprocess
import sys
import warnings
import zipfile
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties, findfont
from PIL import Image, ImageDraw, ImageFont

from materials_data_studio.tools.command_engine import CommandEngine
from materials_data_studio.tools.command_services import DocumentServices
from materials_data_studio.tools.graph_document import load_graph_document, save_graph_document
from materials_data_studio.tools.graph_export import GraphicsSettings, save_graphics
from materials_data_studio.tools.graph_render import IgorMatplotlibRenderer
from materials_data_studio.tools.graph_waves import empty_document, import_columns, put_waves, read_text, text_rows, validate_references
from materials_data_studio.tools.pxp_text import text_runs

from materials_data_studio.version import __version__

SEED=20261117
PALETTE=['#0072B2','#D55E00','#009E73','#CC79A7','#E69F00','#46546A']
XRD_TEMPERATURES_K = (700, 800, 900)
PLOT_TOP_MARGIN = 18
BASE=Path(__file__).resolve().parent
OUT = Path.cwd() / '.test-tmp/graph-editor-baselines/solid-state-v2'


def q(value): return json.dumps(value,ensure_ascii=False)
def rgb(value): return '('+','.join(str(int(value[i:i+2],16)*257) for i in (1,3,5))+')'


class Case:
    def __init__(self,number,slug,title,domain,request,focus):
        self.id=f'd{number:02d}_{slug}'; self.prefix=f'd{number:02d}'
        self.title,self.domain,self.request,self.focus=title,domain,request,focus
        self.rng=np.random.default_rng(SEED+number)
        self.inputs=[];self.commands=[];self.expected_waves={};self.expected_units={}
        self.expected_graphs={};self.main=self.id;self.parameters={};self.notes=[]
        self.checks=[];self.current='';self.visual_requirements={}

    def w(self,name): return self.prefix+'_'+name
    def cmd(self,line): self.commands.append(line)

    def table(self,columns,units=None,name='input.csv',text=()):
        arrays={self.w(k):np.asarray(v) for k,v in columns.items()}
        lengths={len(a) for a in arrays.values()}
        assert len(lengths)==1
        self.inputs.append(dict(file=name,columns=list(arrays),kinds=['Text' if k in text else 'Number' for k in columns],arrays=arrays))
        for k,u in (units or {}).items(): self.unit(k,u)
        return arrays

    def unit(self,name,unit):
        path=self.w(name);self.expected_units[path]=unit
        self.cmd(f'SetScale d,0,0,{q(unit)},{path}')

    def derive(self,name,expression,expected,unit=''):
        values=np.asarray(expected,dtype=float);self.expected_waves[self.w(name)]=values
        self.cmd(f'Make/D/N={len(values)} {self.w(name)}')
        self.cmd(f'{self.w(name)}={expression}')
        self.unit(name,unit)
        return self.w(name)

    def plot(self,name,y,x,xlabel,ylabel,xlim,ylim,*,width=420,height=260,
             host='',rect=None,margins=(72,52,PLOT_TOP_MARGIN,24)):
        self.current=name
        if host:
            create=f'Display/N={name}/HOST={host}/W=('+','.join(map(str,rect))+f') {self.w(y)} vs {self.w(x)}'
        else:
            create=f'Display/N={name}/W=(0,0,548,390) {self.w(y)} vs {self.w(x)}'
        self.cmd(create)
        left,bottom,top,right=margins
        self.cmd(f'ModifyGraph width={width},height={height},margin(left)={left},margin(bottom)={bottom},margin(top)={top},margin(right)={right},gFont="DejaVu Sans",gfSize=11,font="DejaVu Sans",fSize=11,tick=2,mirror=1,minor=1,axThick=0.8,btLen=4.5,stLen=2.5,nticks=5')
        self.cmd(f'SetAxis bottom {xlim[0]},{xlim[1]}')
        self.cmd(f'SetAxis left {ylim[0]},{ylim[1]}')
        self.cmd('Label bottom '+q('\\Z13'+xlabel))
        self.cmd('Label left '+q('\\Z13'+ylabel))
        self.expected_graphs[name]=dict(kind='Graph',host=host,axes={'bottom':dict(limits=list(xlim),label='\\Z13'+xlabel),'left':dict(limits=list(ylim),label='\\Z13'+ylabel)},traces=[dict(name=self.w(y),y=self.w(y),x=self.w(x))])
        return name

    def append(self,y,x):
        self.cmd(f'AppendToGraph {self.w(y)} vs {self.w(x)}')
        self.expected_graphs[self.current]['traces'].append(dict(name=self.w(y),y=self.w(y),x=self.w(x)))

    def style(self,y,ci=0,mode=0,line=0,marker=8,size=2,width=1.6):
        color=PALETTE[ci] if isinstance(ci,int) else ci
        t=self.w(y)
        self.cmd(f'ModifyGraph rgb({t})={rgb(color)},lsize({t})={width},mode({t})={mode},lstyle({t})={line},marker({t})={marker},msize({t})={size}')

    def legend(self,entries,corner='RT',size=10,*,conditions=''):
        x=-3 if corner.startswith('R') else 3
        y=-4 if corner.endswith('T') else 4 if corner.endswith('B') else 0
        text='\\Z'+str(size)+'\n'.join('\\s('+self.w(k)+') '+label for k,label in entries)
        if conditions:
            text+='\n\\Z9'+conditions
        self.cmd(f'Legend/N=legend/A={corner}/X={x}/Y={y}/F=0 '+q(text))

    def note(self,text,corner='LB',size=9):
        x=-3 if corner.startswith('R') else 3;y=-4 if corner.endswith('T') else 4
        self.cmd(f'TextBox/N=note/A={corner}/X={x}/Y={y}/F=0 '+q('\\Z'+str(size)+text))

    def guide(self,x0,y0,x1,y1):
        self.cmd('SetDrawLayer UserBack')
        self.cmd('SetDrawEnv xcoord=bottom,ycoord=left,linefgc=(45000,47000,50000),linethick=0.7')
        self.cmd(f'DrawLine {x0},{y0},{x1},{y1}')

    def layout(self,items):
        self.cmd(f'NewLayout/N={self.main}')
        self.cmd('ModifyGraph gFont="DejaVu Sans",gfSize=11')
        for child,rect in items:
            self.cmd(f'AppendLayoutObject/W={self.main}/R=('+','.join(map(str,rect))+f') graph {child}')
        self.expected_graphs[self.main]=dict(kind='Layout',items=[dict(graph=g,rect=list(r)) for g,r in items])

    def xrd_axes(self,*,intensity=True,numbers=True,strip=False):
        """10 degree major ticks and four intervening, unlabelled 2 degree ticks."""
        options='manTick(bottom)={0,10,0,0},manMinor(bottom)={4,0}'
        bottom=dict(manual_ticks=[0,10,0,0],manual_minor=[4,0])
        left={}
        if intensity:
            options+=',nticks(left)=0,minor(left)=0'
            left.update(tick_count=0,minor_enabled=False)
        if not numbers:
            options+=',noLabel(bottom)=2';bottom['no_label']=2
        if strip:
            options+=',axThick=0,mirror=0,tick=3'
        self.cmd('ModifyGraph '+options)
        axes=self.expected_graphs[self.current]['axes']
        axes['bottom']['style']=bottom;axes['left']['style']=left

    def xrd_strip(self,name,y,x,label,color,*,last=False,height=26):
        self.plot(name,y,x,'2θ (degree)' if last else '','',(10,80),(0,1.08),
            height=height,margins=(72,52 if last else 3,3,24))
        self.style(y,color,mode=1,width=1.25)
        self.xrd_axes(numbers=last,strip=True)
        # Keep the final shared angle axis and its inward ticks visible.
        if last:self.cmd('ModifyGraph axThick(bottom)=0.8,tick(bottom)=2')
        self.cmd(f'TextBox/N=phase_label/A=LC/X=-16/Y=0/F=0 '+q('\\Z9\\K'+rgb(color)+label))
        return name

    def xrd_layout(self,children,*,top=30):
        """Identical physical left/right margins keep all 2theta data areas aligned."""
        items=[];scale=552/516
        for name,height,bottom,upper in children:
            total=(height+bottom+upper)*scale
            items.append((name,(30,top,582,top+total)));top+=total
        assert top<780
        self.layout(items)


def plot_stacked_xrd(case, name, profiles, *, height=310, show_angle_labels=True):
    """Normalize and offset the three annealing profiles on one angle axis."""
    offsets = (0, 120, 240)
    conditions = []
    for index, (temperature, offset, profile) in enumerate(zip(XRD_TEMPERATURES_K, offsets, profiles, strict=True)):
        source = case.w(f'counts{index}')
        maximum = float(np.max(profile))
        trace = case.derive(f'norm{index}', f'100*{source}/{maximum:.17g}', 100*profile/maximum, 'arb. units')
        conditions.append(dict(
            annealing_temperature_K=temperature, source_wave=source, trace=trace,
            y_offset=offset, color=PALETTE[index], label=f'Annealed at {temperature} K',
        ))
        case.checks.append(dict(kind='max', wave=trace, expected=100.))

    case.plot(name,
        'norm0', 'two_theta', '2θ (degree)' if show_angle_labels else '',
        'Intensity / arb. units', (10,80), (-8,365), height=height,
        margins=(72,52 if show_angle_labels else 7,PLOT_TOP_MARGIN,24))
    case.xrd_axes(numbers=show_angle_labels)
    for index, condition in enumerate(conditions):
        wave = f'norm{index}'
        if index:
            case.append(wave, 'two_theta')
        case.style(wave, condition['color'], width=1.25)
        case.cmd(f'ModifyGraph offset({condition["trace"]})={{0,{condition["y_offset"]}}}')

    case.legend([
        (f'norm{index}', f'\\K{rgb(condition["color"])}{condition["label"]}')
        for index, condition in reversed(list(enumerate(conditions)))
    ], size=11)

    case.parameters.update(normalization='100 * I / max(I)', offsets=list(offsets),
        annealing_temperatures_K=list(XRD_TEMPERATURES_K))
    case.visual_requirements.update(intensity_y_label='Intensity / arb. units', intensity_y_ticks=False,
        two_theta_major_degrees=10, two_theta_minor_degrees=2, minor_tick_numbers=False,
        stacked_profiles=dict(graph=name, legend_annotation='legend',
            label_placement='inside the upper right of the plot, clear of the traces',
            legend_order='top to bottom, matching the vertically offset traces',
            conditions_bottom_to_top=conditions))


def first_cases():
    cases=[]
    c=Case(1,'xrd_stacked','XRD：焼鈍温度別の回折パターン','XRD',
        '焼鈍温度700・800・900 Kの合成粉末XRDをそれぞれ最大値100に規格化し、下から順に0・120・240ずらして縦に重ねてください。条件ごとに線色を変え、凡例は描画範囲内の右上で曲線に重ならない場所にまとめてください。グラフタイトルと縦目盛りは省き、縦軸はIntensity / arb. unitsと表記してください。2θは数字付き10度大目盛りと数字なし2度小目盛りにしてください。再編集できる文書と図を保存してください。',
        '規格化・縦オフセット・右上の凡例と曲線の間隔')
    x=np.linspace(10,80,3501);data={'two_theta':x};raw=[]
    for i in range(3):
        y=18+0.08*x+c.rng.normal(0,.45,len(x))
        for p,a,s in [(22.6,380,.14),(31.7,900,.17),(39.4,520,.15),(46.8,650,.20),(56.2,430,.18),(67.5,250,.21)]:
            y+=a*np.exp(-.5*((x-p-.09*i)/(s+.02*i))**2)
        data[f'counts{i}']=y;raw.append(y)
    c.table(data,{'two_theta':'degree',**{f'counts{i}':'count' for i in range(3)}})
    c.parameters={'source':'synthetic powder profiles'}
    plot_stacked_xrd(c, c.main, raw)
    cases.append(c)

    c=Case(2,'xrd_profile_residual','XRD：3相のリートベルト形式表示','XRD',
        '合成の観測データと提示済み計算曲線を最上段で重ね、その下に3相のBragg位置を相ごとに別段で表示し、一番下に観測−計算の残差を描いてください。縦軸の目盛りはなくし、強度ラベルはIntensity / arb. units、2θの大目盛りは数字付き10度、小目盛りは数字なし2度にしてください。追加の構造解析・fitは行わないでください。',
        '実験＋計算 → 3相のピーク位置 → 最下段の残差・共通2θ・縦目盛りなし')
    x=np.linspace(10,80,2801);model=22+.10*x
    phases=[([21.2,30.6,38.8,47.4,57.1,67.8],[420,1100,610,750,390,220]),
            ([25.4,34.2,44.6,53.1,64.4,72.1],[120,180,95,140,110,80]),
            ([18.6,28.3,41.5,50.2,61.7],[70,95,65,85,55])]
    for phase,(positions,amplitudes) in enumerate(phases):
        for p,a in zip(positions,amplitudes,strict=True):
            model+=a*np.exp(-.5*((x-p)/(.14+.025*phase+.0005*p))**2)
    observed=model+c.rng.normal(0,4,len(x))
    c.table({'two_theta':x,'observed':observed,'calculated':model,'zero':np.zeros(len(x))},{'two_theta':'degree','observed':'count','calculated':'count','zero':'count'})
    for i,(positions,_) in enumerate(phases):
        c.table({f'phase{i}_x':positions,f'phase{i}_y':[.8]*len(positions)},
            {f'phase{i}_x':'degree',f'phase{i}_y':'arb. units'},f'phase_{i+1}_positions.csv')
    c.derive('observed_arb',f'{c.w("observed")}/1000',observed/1000,'arb. units')
    c.derive('calculated_arb',f'{c.w("calculated")}/1000',model/1000,'arb. units')
    c.derive('residual',f'({c.w("observed")}-{c.w("calculated")})/1000',(observed-model)/1000,'arb. units')
    top=c.main+'_profile';bot=c.main+'_residual'
    c.plot(top,
        'observed_arb','two_theta','','Intensity / arb. units',(10,80),(-.01,1.30),height=350,margins=(72,7,PLOT_TOP_MARGIN,24))
    c.style('observed_arb',0,mode=3,marker=8,size=1.25,width=.6)
    c.append('calculated_arb','two_theta');c.style('calculated_arb',1,width=1.5)
    c.xrd_axes(numbers=False);c.legend([('observed_arb','Observed (demo)'),('calculated_arb','Calculated (supplied)')])
    children=[(top,350,7,PLOT_TOP_MARGIN)]
    for i,color in enumerate([PALETTE[4],PALETTE[2],PALETTE[3]]):
        name=c.main+f'_phase{i+1}'
        c.xrd_strip(name,f'phase{i}_y',f'phase{i}_x',f'Phase {chr(65+i)}',color,height=23)
        children.append((name,23,3,3))
    residual_half_range=1.31*78/350/2
    c.plot(bot,'zero','two_theta','2θ (degree)','',(10,80),(-residual_half_range,residual_half_range),height=78,margins=(72,52,8,24))
    c.style('zero',5,width=.65);c.append('residual','two_theta');c.style('residual',0,width=.8)
    c.xrd_axes();c.note('Observed − calculated','RT',size=9)
    c.xrd_layout(children+[(bot,78,52,8)], top=75)
    c.parameters={'intensity_scale_counts_per_arb_unit':1000,'phase_count':3,'residual':'(observed - calculated) / 1000',
        'residual_display':'same intensity-to-pixel scale as the observed/calculated panel; no magnification'}
    c.visual_requirements=dict(intensity_y_label='Intensity / arb. units',intensity_y_ticks=False,
        two_theta_major_degrees=10,two_theta_minor_degrees=2,minor_tick_numbers=False,
        panel_order=['observed_and_calculated','phase_A_positions','phase_B_positions','phase_C_positions','observed_minus_calculated'],
        peak_correspondence_guides=False,bragg_rows=3)
    c.notes.append('計算曲線・3相の参照位置は合成した固定入力。実際の構造精密化やRietveld解析の成功を主張する作例ではない。添付された未発表データは使わない。')
    cases.append(c)

    c=Case(3,'mpms_zfc_fc','MPMS：ZFC / FCのモル磁化率','MPMS',
        '磁場1000 Oe、試料10 mg、式量100 g/molとして、ZFC/FCのmomentをモル磁化率へ換算し、温度に対して重ねてください。各条件を図に記載してください。',
        '質量と式量による単位換算・ZFC/FCの対応・条件注記')
    t=np.linspace(2,300,240);h=np.full_like(t,1000.);n=10/1000/100
    irr=1/(1+np.exp((t-85)/8));base=.001+1.2/(t+50)
    fc=base+.004*irr;zfc=base*(1-.9*irr)
    c.table({'temperature':t,'field_oe':h,'moment_zfc':zfc*h*n,'moment_fc':fc*h*n},
        {'temperature':'K','field_oe':'Oe','moment_zfc':'emu','moment_fc':'emu'})
    c.parameters={'sample_mass_mg':10.,'molar_mass_g_mol':100.,'field_oe':1000.,'moles':n}
    for name,truth in [('zfc',zfc),('fc',fc)]:c.derive('chi_'+name,f'{c.w("moment_"+name)}/{c.w("field_oe")}/{n:.17g}',truth,'cm^3 mol^-1')
    c.plot(c.main,'chi_zfc','temperature','Temperature (K)','χ\\Bm\\M (cm\\S3\\M mol\\S−1\\M)',(0,310),(0,.031))
    c.style('chi_zfc',0);c.append('chi_fc','temperature');c.style('chi_fc',1,line=1)
    c.legend([('chi_zfc','ZFC'),('chi_fc','FC')],
        conditions='H = 1000 Oe\nSample mass = 10 mg\nMolar mass = 100 g mol\\S−1\\M')
    cases.append(c)

    c=Case(4,'mpms_curie_weiss','MPMS：背景補正した逆磁化率','MPMS',
        '試料10 mg、式量100 g/mol、磁場1000 Oeを使い、χ0=0.00015 cm³/molを引いた逆モル磁化率を表示してください。提示されたCurie–Weiss基準線と重ねてください。',
        '背景補正の順序・逆数変換・温度範囲・基準線の意味')
    t=np.linspace(100,350,51);n=1e-4;chi0=.00015;C=1.25;theta=-18.
    chi=chi0+C/(t-theta);reference=(t-theta)/C
    c.table({'temperature':t,'field_oe':np.full_like(t,1000.),'moment':chi*1000*n,'reference':reference},
        {'temperature':'K','field_oe':'Oe','moment':'emu','reference':'mol cm^-3'})
    c.parameters={'sample_mass_mg':10.,'molar_mass_g_mol':100.,'chi0_cm3_mol':chi0,'reference_C_cm3_K_mol':C,'reference_theta_K':theta}
    c.derive('chi',f'{c.w("moment")}/{c.w("field_oe")}/0.0001',chi,'cm^3 mol^-1')
    c.derive('inv_chi',f'1/({c.w("chi")}-0.00015)',reference,'mol cm^-3')
    c.plot(c.main,'reference','temperature','Temperature (K)','(χ\\Bm\\M − χ\\B0\\M)\\S−1\\M (mol cm\\S−3\\M)',(90,360),(70,315))
    c.style('reference',1,line=1);c.append('inv_chi','temperature');c.style('inv_chi',0,mode=3,size=1.7)
    c.legend([('inv_chi','Converted data'),('reference','Supplied C–W line')],'LT')
    c.note('C = 1.25 cm\\S3\\M K mol\\S−1\\M\nθ = −18 K\nχ\\B0\\M = 1.5 × 10\\S−4\\M cm\\S3\\M mol\\S−1\\M','RB')
    cases.append(c)

    c=Case(5,'mpms_mh','MPMS：M–Hと保磁力付近のinset','MPMS',
        '試料10 mg、式量100 g/molとして、emuをμB/f.u.、OeをTに変換してください。磁場の増減の順序を保持してM–Hを描き、±0.7 Tをinsetで拡大してください。',
        '磁場・磁化の換算・測定方向・insetの独立範囲')
    hup=np.linspace(-5,5,601);hdown=hup[::-1];n=1e-4;factor=5585.6947
    up=.95*np.tanh((hup-.28)/.13)+.025*hup;down=.95*np.tanh((hdown+.28)/.13)+.025*hdown
    c.table({'field_up':hup*10000,'field_down':hdown*10000,'moment_up':up*n*factor,'moment_down':down*n*factor},
        {'field_up':'Oe','field_down':'Oe','moment_up':'emu','moment_down':'emu'})
    c.parameters={'sample_mass_mg':10.,'molar_mass_g_mol':100.,'emu_per_mol_per_muB':factor,'Oe_per_T':10000.,'temperature_K':5.}
    for branch,h,m in [('up',hup,up),('down',hdown,down)]:
        c.derive('H_'+branch,f'{c.w("field_"+branch)}/10000',h,'T')
        c.derive('M_'+branch,f'{c.w("moment_"+branch)}/0.0001/5585.6947',m,'muB f.u.^-1')
    c.plot(c.main,'M_up','H_up','Magnetic field (T)','Magnetization (μB f.u.\\S−1\\M)',(-5,5),(-1.2,1.2))
    c.style('M_up',0);c.append('M_down','H_down');c.style('M_down',1,line=1)
    c.legend([('M_up','Increasing field'),('M_down','Decreasing field')],'LT',
        conditions='T = 5 K\nSample mass = 10 mg\nMolar mass = 100 g mol\\S−1\\M')
    c.guide(-5,0,5,0)
    child=c.main+'_inset'
    c.plot(child, 'M_up','H_up','H (T)','M',(-.7,.7),(-1.05,1.05),width=145,height=100,host=c.main,rect=(.57,.44,.94,.84),margins=(34,29,9,8))
    c.cmd('ModifyGraph gfSize=8,fSize=8,nticks=3')
    c.cmd('Label bottom '+q('\\Z9H (T)'));c.cmd('Label left '+q('\\Z9M'))
    c.expected_graphs[child]['axes']['bottom']['label']='\\Z9H (T)';c.expected_graphs[child]['axes']['left']['label']='\\Z9M'
    c.style('M_up',0,width=1.2);c.append('M_down','H_down');c.style('M_down',1,line=1,width=1.2)
    c.checks.extend([dict(kind='increasing',wave=c.w('H_up')),dict(kind='decreasing',wave=c.w('H_down'))]);cases.append(c)

    c=Case(6,'ppms_rho_t','PPMS：磁場別の低温抵抗率','PPMS',
        '幅0.12 cm、厚さ0.02 cm、電圧端子間0.6 cmとして抵抗をmΩ cmへ換算し、0・3・6 Tのρ–Tを比較してください。転移付近をinsetで拡大してください。',
        '試料形状・抵抗率の換算・磁場ラベル・低温転移の拡大')
    t=np.linspace(1.8,30,451);geometry=.12*.02/.6;cols={'temperature':t};truth=[]
    for i,tc in enumerate([8.8,7.7,6.3]):
        rho=.002+(.65+.0018*t+.025*i)/(1+np.exp(-(t-tc)/.15));truth.append(rho)
        cols[f'resistance{i}']=rho/1000/geometry
    c.table(cols,{'temperature':'K',**{f'resistance{i}':'ohm' for i in range(3)}})
    c.parameters={'width_cm':.12,'thickness_cm':.02,'voltage_length_cm':.6,'fields_T':[0,3,6]}
    for i,rho in enumerate(truth):c.derive(f'rho{i}',f'{c.w(f"resistance{i}")}*0.12*0.02/0.6*1000',rho,'mohm cm')
    c.plot(c.main,'rho0','temperature','Temperature (K)','Resistivity (mΩ cm)',(0,30),(0,.86))
    for i in range(3):
        if i:c.append(f'rho{i}','temperature')
        c.style(f'rho{i}',i,line=i)
    c.legend([(f'rho{i}',f'μ\\B0\\MH = {3*i} T') for i in range(3)],'LT')
    c.cmd('TextBox/N=sample_geometry/A=LB/X=33/Y=18/F=0 '+q('\\Z9Area = 0.12 × 0.02 cm²\nLead spacing = 0.6 cm'))
    child=c.main+'_inset';c.plot(child, 'rho0','temperature','T (K)','ρ',(5.5,9.8),(0,.83),width=145,height=105,host=c.main,rect=(.57,.44,.94,.84),margins=(33,29,9,8))
    c.cmd('ModifyGraph gfSize=8,fSize=8,nticks=3');c.cmd('Label bottom '+q('\\Z9T (K)'));c.cmd('Label left '+q('\\Z9ρ'))
    c.expected_graphs[child]['axes']['bottom']['label']='\\Z9T (K)';c.expected_graphs[child]['axes']['left']['label']='\\Z9ρ'
    for i in range(3):
        if i:c.append(f'rho{i}','temperature')
        c.style(f'rho{i}',i,line=i,width=1.2)
    cases.append(c)

    c=Case(7,'ppms_low_t_cp','PPMS：Cp/T–T²と誤差棒','PPMS',
        '試料5 mg、式量100 g/molとしてμJ/Kをモル比熱に換算し、Cp/TをT²に対して表示してください。測定誤差もCp/Tの単位に変換し、提示済みのγ・βの直線と重ねてください。',
        '比熱と誤差の換算・T²軸・γ/β基準線・科学単位')
    t=np.linspace(2,8,41);n=5/1000/100;gamma=.012;beta=.00024
    reference=1000*(gamma+beta*t*t);sigma=.35*np.ones_like(t)
    cp_molar=(reference+c.rng.normal(0,sigma))*t/1000
    c.table({'temperature':t,'cp_uj_k':cp_molar*n*1e6,'cp_error_uj_k':sigma*t/1000*n*1e6,'reference':reference},
        {'temperature':'K','cp_uj_k':'uJ K^-1','cp_error_uj_k':'uJ K^-1','reference':'mJ mol^-1 K^-2'})
    c.parameters={'sample_mass_mg':5.,'molar_mass_g_mol':100.,'gamma_J_mol_K2':gamma,'beta_J_mol_K4':beta,'error_meaning':'one-sigma supplied Cp uncertainty'}
    c.derive('T2',f'{c.w("temperature")}^2',t*t,'K^2')
    c.derive('cp_over_t',f'{c.w("cp_uj_k")}/1000000/0.00005/{c.w("temperature")}*1000',cp_molar/t*1000,'mJ mol^-1 K^-2')
    c.derive('cp_over_t_error',f'{c.w("cp_error_uj_k")}/1000000/0.00005/{c.w("temperature")}*1000',sigma,'mJ mol^-1 K^-2')
    c.plot(c.main,'reference','T2','T\\S2\\M (K\\S2\\M)','C\\Bp\\M/T (mJ mol\\S−1\\M K\\S−2\\M)',(0,70),(8,33))
    c.style('reference',1);c.append('cp_over_t','T2');c.style('cp_over_t',0,mode=3,size=2.2)
    c.cmd(f'ErrorBars {c.w("cp_over_t")} Y,wave=({c.w("cp_over_t_error")},{c.w("cp_over_t_error")})')
    c.legend([('cp_over_t','Observations (bars: 1σ)'),('reference','Supplied γ + βT\\S2\\M')],'LT',
        conditions='Sample mass = 5 mg\nMolar mass = 100 g mol\\S−1\\M')
    c.note('γ = 12 mJ mol\\S−1\\M K\\S−2\\M\nβ = 0.24 mJ mol\\S−1\\M K\\S−4\\M','RB')
    cases.append(c)

    c=Case(8,'ppms_cp_anomaly','PPMS：比熱異常の磁場依存','PPMS',
        '0・4・8 Tのモル比熱を同じ温度軸で比較してください。ピークの移動が読める線種と凡例にし、各系列を個別に再編集できる状態で保存してください。',
        '比熱異常・系列の対応・ピーク移動・モル単位')
    t=np.linspace(2,28,261);cols={'temperature':t}
    for i,tc in enumerate([12.,10.5,8.5]):cols[f'cp{i}']=.015*t+.0001*t**3+2*np.exp(-.5*((t-tc)/(1.05+.15*i))**2)
    c.table(cols,{'temperature':'K',**{f'cp{i}':'J mol^-1 K^-1' for i in range(3)}})
    c.parameters={'fields_T':[0,4,8],'data_state':'already molar Cp; no mass conversion requested'}
    c.plot(c.main,'cp0','temperature','Temperature (K)','C\\Bp\\M (J mol\\S−1\\M K\\S−1\\M)',(0,30),(0,3.2))
    for i in range(3):
        if i:c.append(f'cp{i}','temperature')
        c.style(f'cp{i}',i,line=i)
    c.legend([(f'cp{i}',f'μ\\B0\\MH = {4*i} T') for i in range(3)],'LT');cases.append(c)

    c=Case(9,'magnetoresistance','磁気抵抗：ゼロ磁場基準のMR','固体物性',
        '各温度のR(0)を基準にMR=100[R(H)−R(0)]/R(0)を計算し、磁場−9〜9 Tの同じ範囲で比較してください。縦軸は%としてください。',
        '温度ごとのゼロ磁場基準・%変換・正負磁場・対称性')
    h=np.linspace(-9,9,361);cols={'field':h};truth=[]
    for i,(a,r0) in enumerate([(0.25,.014),(.09,.019),(.03,.028)]):
        mr=a*h*h/(1+(h/8)**2);truth.append(mr);cols[f'resistance{i}']=r0*(1+mr/100)
    c.table(cols,{'field':'T',**{f'resistance{i}':'ohm' for i in range(3)}})
    c.parameters={'temperatures_K':[5,50,150],'R0_ohm':[.014,.019,.028],'reference':'H=0 row; separate R0 for each temperature'}
    for i,(mr,r0) in enumerate(zip(truth,c.parameters['R0_ohm'],strict=True)):
        c.derive(f'MR{i}',f'100*({c.w(f"resistance{i}")}-{r0})/{r0}',mr,'%')
        c.checks.append(dict(kind='even',wave=c.w(f'MR{i}')))
    c.plot(c.main,'MR0','field','Magnetic field (T)','MR (%)',(-9,9),(-.5,11))
    for i in range(3):
        if i:c.append(f'MR{i}','field')
        c.style(f'MR{i}',i,line=i)
    c.legend([(f'MR{i}',f'{temp} K') for i,temp in enumerate([5,50,150])],'LT');c.guide(-9,0,9,0);cases.append(c)

    c=Case(10,'hall_antisym','Hall効果：反対称化','固体物性',
        '同じ|H|の±Hデータの組を使ってρyx(H)=[ρraw(H)−ρraw(−H)]/2を作り、元の信号と重ねてください。磁場はT、横抵抗率はμΩ cmのまま保持してください。',
        '±Hの対応・反対称化の符号・偶成分の除去・元データ保持')
    h=np.linspace(-9,9,361);raw=.055*h+.006*h*h+.04;opposite=-.055*h+.006*h*h+.04;anti=.055*h
    c.table({'field':h,'raw':raw,'opposite':opposite},{'field':'T','raw':'uohm cm','opposite':'uohm cm'})
    c.derive('antisym',f'({c.w("raw")}-{c.w("opposite")})/2',anti,'uohm cm')
    c.parameters={'paired_rows':'raw(H), opposite=raw(-H) for the same row H','reference_slope_uohm_cm_T':.055}
    c.plot(c.main,'raw','field','Magnetic field (T)','ρ\\Byx\\M (μΩ cm)',(-9,9),(-.65,1.2))
    c.style('raw',5,line=1,width=1.15);c.append('antisym','field');c.style('antisym',0,width=1.9)
    c.legend([('raw','Raw transverse signal'),('antisym','Antisymmetrized signal')],'LT');c.guide(-9,0,9,0)
    c.checks.append(dict(kind='odd',wave=c.w('antisym')));cases.append(c)
    return cases


def additional_cases():
    cases=[]
    c=Case(11,'arrhenius','電気輸送：Arrhenius表示','固体物性',
        '提示された抵抗率を1000/Tに対するln[ρ/(1 Ω cm)]へ変換してください。36 meVの活性化エネルギーから用意した基準線を添えてください。',
        '1000/Tと1/Tの係数差・対数の無次元化・基準線の説明')
    t=np.linspace(100,300,65);kb=8.617333262145e-5;ea=.036
    ideal=.18*np.exp(ea/(kb*t));rho=ideal*np.exp(.015*np.sin(t/9))
    c.table({'temperature':t,'rho':rho,'reference':np.log(ideal)},{'temperature':'K','rho':'ohm cm','reference':'dimensionless'})
    c.parameters={'reference_Ea_eV':ea,'kB_eV_K':kb,'resistivity_reference_ohm_cm':1.,'model_reference_is_supplied':True}
    c.derive('invT1000',f'1000/{c.w("temperature")}',1000/t,'1000 K^-1')
    c.derive('lnrho',f'ln({c.w("rho")})',np.log(rho),'dimensionless')
    c.plot(c.main,'reference','invT1000','1000/T (K\\S−1\\M)','ln[ρ / (1 Ω cm)]',(3,10.4),(-.6,2.8))
    c.style('reference',1,line=1);c.append('lnrho','invT1000');c.style('lnrho',0,mode=3,size=1.8)
    c.legend([('lnrho','Transformed observations'),('reference','Supplied reference (E\\Ba\\M = 36 meV)')],'LT');cases.append(c)

    c=Case(12,'mott_vrh','電気輸送：3D Mott VRH表示','固体物性',
        '3D Mottの指数1/4を明示して、ln[σ/(1 S cm⁻¹)]をT⁻¹/⁴に対して表示してください。次元や伝導機構の自動判定は加えず、提示したモデル線と比較してください。',
        '指数の指定・対数変換・軸単位・モデル仮定の明示')
    t=np.geomspace(30,300,61);t0=2.5e5;sigma0=2e4
    expected=np.log(sigma0)-(t0/t)**.25;sigma=np.exp(expected+.012*np.cos(t/13))
    c.table({'temperature':t,'sigma':sigma,'reference':expected},{'temperature':'K','sigma':'S cm^-1','reference':'dimensionless'})
    c.parameters={'dimensionality':3,'exponent':.25,'T0_K':t0,'sigma0_S_cm':sigma0,'model_selection':'specified by task'}
    c.derive('Tquarter',f'{c.w("temperature")}^(-0.25)',t**(-.25),'K^-1/4')
    c.derive('lnsigma',f'ln({c.w("sigma")})',np.log(sigma),'dimensionless')
    c.plot(c.main,'reference','Tquarter','T\\S−1/4\\M (K\\S−1/4\\M)','ln[σ / (1 S cm\\S−1\\M)]',(.23,.44),(0,5.5))
    c.style('reference',1,line=1);c.append('lnsigma','Tquarter');c.style('lnsigma',0,mode=3,size=1.8)
    c.legend([('lnsigma','Transformed observations'),('reference','3D Mott reference (T\\B0\\M = 2.5 × 10\\S5\\M K)')],'RT');cases.append(c)

    c=Case(13,'bands_dos','電子状態：バンド構造とDOS','固体科学',
        '準備済みのバンドとDOSを横に配置してください。Γ–X–M–Γの文字目盛、EF=0の基準線、共通のエネルギー範囲−3〜3 eVを設定してください。',
        '高対称点の文字目盛・EF基準・共通エネルギー軸・横配置')
    k=np.linspace(0,3,241);s=np.sin(np.pi*k/3)**2
    bands=[-.6-.5*s,-1.3-.5*np.cos(np.pi*k/3)**2,-2.25-.35*np.cos(2*np.pi*k/3),
           .65+.65*s,1.7+.45*np.cos(np.pi*k/3),2.45+.25*np.sin(2*np.pi*k/3)]
    cols={'kpath':k,**{f'band{i}':b for i,b in enumerate(bands)}}
    c.table(cols,{'kpath':'path coordinate',**{f'band{i}':'eV' for i in range(6)}})
    c.table({'ticks':[0,1,2,3],'labels':np.array(['Γ','X','M','Γ'])},name='symmetry_points.csv',text=('labels',))
    energy=np.linspace(-3,3,401)
    dos=3*np.exp(-.5*((energy+1.35)/.32)**2)+2.2*np.exp(-.5*((energy+2.3)/.2)**2)+2.6*np.exp(-.5*((energy-1.35)/.35)**2)+1.8*np.exp(-.5*((energy-2.45)/.23)**2)
    dos[(energy>-.6)&(energy<.65)]=0
    c.table({'energy':energy,'dos':dos},{'energy':'eV','dos':'states eV^-1 f.u.^-1'},'dos.csv')
    c.parameters={'energy_reference':'EF=0','symmetry_labels':['Γ','X','M','Γ'],'reference_gap_eV':1.25,'data_origin':'analytic synthetic bands and DOS, not a DFT calculation'}
    band=c.main+'_bands';dosgraph=c.main+'_dos'
    c.plot(band,'band0','kpath','Wave-vector path','E − E\\BF\\M (eV)',(0,3),(-3,3),width=290,height=455,margins=(61,45,PLOT_TOP_MARGIN,12))
    for i in range(6):
        if i:c.append(f'band{i}','kpath')
        c.style(f'band{i}',0 if i<3 else 1,width=1.6)
    c.cmd(f'ModifyGraph userticks(bottom)={{{c.w("ticks")},{c.w("labels")}}}')
    for kk in [1,2]:c.guide(kk,-3,kk,3)
    c.guide(0,0,3,0)
    c.plot(dosgraph,'energy','dos','DOS','E − E\\BF\\M (eV)',(0,3.6),(-3,3),width=95,height=455,margins=(49,45,PLOT_TOP_MARGIN,13))
    c.style('energy',2,width=1.6);c.guide(0,0,3.6,0)
    c.layout([(band,(24,90,405.15,661.2)),(dosgraph,(422,90,586.85,661.2))]);cases.append(c)

    c=Case(14,'phonon','格子振動：フォノン分散','固体科学',
        '6本のフォノン分枝をΓ–X–M–Γに沿って表示してください。音響3分枝と光学3分枝を色・線種で区別し、周波数の単位とゼロ線を付けてください。',
        '音響・光学分枝の識別・高対称点・ゼロ周波数の扱い')
    k=np.linspace(0,3,241);a=np.abs(np.sin(np.pi*k/3))
    modes=[1.45*a,2.65*a,4.4*a,7.05+.38*np.sin(np.pi*k/3)**2,8.1+.45*np.cos(2*np.pi*k/3),9.1+.35*np.sin(np.pi*k/3)]
    c.table({'kpath':k,**{f'mode{i}':v for i,v in enumerate(modes)}},{'kpath':'path coordinate',**{f'mode{i}':'THz' for i in range(6)}})
    c.table({'ticks':[0,1,2,3],'labels':np.array(['Γ','X','M','Γ'])},name='symmetry_points.csv',text=('labels',))
    c.parameters={'acoustic_branches':3,'optical_branches':3,'data_origin':'stable analytic synthetic phonons'}
    c.plot(c.main,'mode0','kpath','Wave-vector path','Frequency (THz)',(0,3),(-.3,10.2))
    for i in range(6):
        if i:c.append(f'mode{i}','kpath')
        c.style(f'mode{i}',0 if i<3 else 1,line=0 if i<3 else 1)
    c.cmd(f'ModifyGraph userticks(bottom)={{{c.w("ticks")},{c.w("labels")}}}')
    c.legend([('mode0','Acoustic branches'),('mode3','Optical branches')],'RC')
    for kk in [1,2]:c.guide(kk,-.3,kk,10.2)
    c.guide(0,0,3,0);cases.append(c)

    c=Case(15,'nyquist','複素インピーダンス：Nyquist','固体科学',
        '2条件の複素インピーダンスをRe Zに対する−Im Zで描いてください。虚部の符号を明示し、XとYの1 Ωが同じ長さになるように設定してください。',
        '虚部の符号・Ω単位・等しい物理縮尺・半円の形')
    f=np.geomspace(.01,1e6,401);cols={'frequency':f};truth=[]
    for i,(rct,cap) in enumerate([(1000.,2e-6),(600.,4e-6)]):
        w=2*np.pi*f*rct*cap;z=80+rct/(1+1j*w)
        cols[f'real{i}']=z.real;cols[f'imag{i}']=z.imag;truth.append(-z.imag)
    c.table(cols,{'frequency':'Hz',**{f'{part}{i}':'ohm' for part in ['real','imag'] for i in range(2)}})
    c.parameters={'series_R_ohm':80.,'parallel_R_ohm':[1000.,600.],'parallel_C_F':[2e-6,4e-6],'equal_axis_scale':True}
    for i,y in enumerate(truth):c.derive(f'minus_imag{i}',f'-{c.w(f"imag{i}")}',y,'ohm')
    c.plot(c.main,'minus_imag0','real0','Re Z (Ω)','−Im Z (Ω)',(0,1150),(0,632.5),width=420,height=231)
    c.style('minus_imag0',0);c.append('minus_imag1','real1');c.style('minus_imag1',1,line=1)
    c.legend([('minus_imag0','Condition A'),('minus_imag1','Condition B')],'RT');cases.append(c)

    c=Case(16,'raman','振動分光：温度別Ramanスペクトル','固体科学',
        '200・300・400 KのRamanスペクトルをY方向に0・380・760ずらし、ピークの温度変化を比較してください。横軸はRaman shift（cm⁻¹）としてください。',
        '波数単位・表示offset・微小なピーク移動・生データの保持')
    x=np.linspace(100,800,2801);cols={'shift':x}
    for i in range(3):
        y=18+.015*x+c.rng.normal(0,1.05,len(x))
        for p,a,g in [(196,220,4.5),(403,300,6),(615,180,8.5)]:y+=a/(1+((x-(p-1.2*i))/(g+.8*i))**2)
        cols[f'intensity{i}']=y
    c.table(cols,{'shift':'cm^-1',**{f'intensity{i}':'a.u.' for i in range(3)}})
    c.parameters={'temperatures_K':[200,300,400],'offsets':[0,380,760],'source':'synthetic Lorentzian phonon spectra'}
    c.plot(c.main,'intensity0','shift','Raman shift (cm\\S−1\\M)','Intensity + offset (a.u.)',(100,800),(0,1200))
    for i in range(3):
        if i:c.append(f'intensity{i}','shift')
        c.style(f'intensity{i}',i,width=1.25);c.cmd(f'ModifyGraph offset({c.w(f"intensity{i}")})={{0,{380*i}}}')
    c.legend([(f'intensity{i}',f'{200+100*i} K') for i in range(3)],'RT');cases.append(c)

    c=Case(17,'xps','光電子分光：逆向きエネルギー軸と成分・残差','固体科学',
        'XPSの結合エネルギーを左から右へ小さくなる軸にしてください。観測、提示済みの全モデル、成分A/B、背景を重ね、下に観測−モデルの残差を配置してください。',
        'エネルギー軸の反転・成分と全モデルの区別・残差の符号')
    energy=np.linspace(524,536,601);a=600*np.exp(-.5*((energy-530.8)/.55)**2);b=220*np.exp(-.5*((energy-532.2)/.8)**2);bg=80+3*(energy-524)
    model=a+b+bg;obs=model+c.rng.normal(0,4,len(energy))
    c.table({'energy':energy,'component_a':a,'component_b':b,'background':bg,'model':model,'observed':obs,'zero':np.zeros_like(energy)},
        {'energy':'eV',**{name:'count' for name in ['component_a','component_b','background','model','observed','zero']}})
    c.derive('residual',f'{c.w("observed")}-{c.w("model")}',obs-model,'count')
    c.parameters={'energy_axis':'decreasing left to right','components':'supplied A and B; no chemical-state assignment or refit'}
    top=c.main+'_components';bot=c.main+'_residual'
    c.plot(top,'observed','energy','Binding energy (eV)','Intensity (count)',(524,536),(0,910))
    c.cmd('ModifyGraph reverse(bottom)=1');c.expected_graphs[top]['axes']['bottom']['reverse']=True
    c.style('observed',5,width=.7)
    for name,ci,line in [('component_a',0,1),('component_b',2,1),('background',4,2),('model',1,0)]:
        c.append(name,'energy');c.style(name,ci,line=line,width=1.55)
    c.legend([('observed','Observed'),('model','Supplied total'),('component_a','Component A'),('component_b','Component B'),('background','Background')],'LT',9)
    c.plot(bot,'zero','energy','Binding energy (eV)','Residual (count)',(524,536),(-18,18),height=100)
    c.cmd('ModifyGraph reverse(bottom)=1');c.expected_graphs[bot]['axes']['bottom']['reverse']=True
    c.style('zero',5,line=1,width=.7);c.append('residual','energy');c.style('residual',0,width=.8)
    c.legend([('residual','Observed − supplied model')],size=9)
    c.layout([(top,(22,25,590,536)),(bot,(22,542,590,772))]);cases.append(c)

    c=Case(18,'tauc','光学特性：直接遷移Taucプロット','固体科学',
        '直接遷移を仮定した(αhν)²を光子エネルギーに対して描いてください。値は10¹⁰ eV² cm⁻²単位とし、提示済みの線形外挿とEg=1.8 eVの交点を示してください。',
        '遷移モデルの明示・物理量のべき乗・桁の単位・外挿の意味')
    energy=np.linspace(1.3,3.4,211);eg=1.8
    alpha=np.where(energy>=eg,np.sqrt(5e10*np.maximum(energy-eg,0))/energy,1500*np.exp((energy-eg)/.09))
    alpha*=1+c.rng.normal(0,.003,len(energy))
    ref=5*(energy-eg);ref[(energy<1.65)|(energy>2.75)]=np.nan
    c.table({'energy':energy,'alpha':alpha,'reference':ref},{'energy':'eV','alpha':'cm^-1','reference':'1e10 eV^2 cm^-2'})
    c.derive('tauc',f'({c.w("alpha")}*{c.w("energy")})^2/10000000000',(alpha*energy)**2/1e10,'1e10 eV^2 cm^-2')
    c.parameters={'transition':'direct allowed; specified by task','reference_Eg_eV':eg,'vertical_scale':1e10,'reference_line':'supplied, not fitted in this task'}
    c.plot(c.main,'tauc','energy','Photon energy hν (eV)','(αhν)\\S2\\M (10\\S10\\M eV\\S2\\M cm\\S−2\\M)',(1.2,3.5),(-.9,8.5))
    c.style('tauc',0);c.append('reference','energy');c.style('reference',1,line=1)
    c.legend([('tauc','Transformed absorption (direct allowed)'),('reference','Supplied linear extrapolation')],'LT')
    c.guide(1.2,0,3.5,0);c.guide(eg,-.8,eg,1)
    c.note('Reference E\\Bg\\M = 1.8 eV','RB');cases.append(c)
    return cases


def xrd_condition_cases():
    """Synthetic references and condition maps; never derived from supplied images."""
    cases=[]
    c=Case(19,'xrd_parent_comparison','XRD：焼鈍温度別の回折パターンと母構造','XRD',
        '焼鈍温度700・800・900 Kの合成粉末XRDをそれぞれ最大値100に規格化し、下から順に0・120・240ずらして縦に重ねてください。条件ごとに線色を変え、凡例は描画範囲内の右上で曲線に重ならない場所にまとめてください。実験パターンの下に2つの母構造モデルのsimピークを相対強度付きの棒として別段に置いてください。実験とsimを結ぶ垂直線は不要です。グラフタイトルと縦目盛りは省き、縦軸はIntensity / arb. unitsと表記してください。2θは数字付き10度大目盛りと数字なし2度小目盛りにしてください。',
        '縦オフセット・右上の凡例と曲線の間隔・実験パターンの下の母構造simピーク')
    x=np.linspace(10,80,2801)
    components=[]
    shell=np.array(sorted({h*h+k*k+l*l for h in range(5) for k in range(5) for l in range(5)}-{0}))
    for i,a in enumerate([6.24,6.38]):
        sine=1.5406*np.sqrt(shell)/(2*a);valid=sine<1
        positions=2*np.rad2deg(np.arcsin(sine[valid]));s= shell[valid]
        keep=(positions>=10)&(positions<=80);positions=positions[keep];s=s[keep]
        heights=(.25+.75*np.sin(1.7*s+.6*i)**2)*np.exp(-.025*positions)
        heights/=heights.max()
        c.table({f'parent{i}_x':positions,f'parent{i}_height':heights},
            {f'parent{i}_x':'degree',f'parent{i}_height':'arb. units'},f'parent_{chr(65+i)}_simulation.csv')
        component=np.zeros_like(x)
        for position,weight in zip(positions,heights,strict=True):
            component+=weight*np.exp(-.5*((x-position)/(.12+.001*position))**2)
        components.append(component)

    # The synthetic patterns progress from parent A toward parent B as annealing temperature increases.
    component_weights = [(0.95, 0.05), (0.55, 0.45), (0.10, 0.90)]
    profiles = [
        18 + .08*x + 900*(weight_a*components[0] + weight_b*components[1]) + c.rng.normal(0, 2, len(x))
        for weight_a, weight_b in component_weights
    ]
    c.table({'two_theta':x, **{f'counts{i}':profile for i,profile in enumerate(profiles)}},
        {'two_theta':'degree', **{f'counts{i}':'count' for i in range(len(profiles))}})
    c.parameters=dict(wavelength_angstrom=1.5406,demo_cubic_lattice_angstrom=[6.24,6.38],
        position_formula='2 arcsin(lambda sqrt(h²+k²+l²) / (2 a))',
        simulation_intensities='illustrative deterministic weights; not structure-factor calculation',
        synthetic_parent_weights=component_weights)
    main = c.main+'_observed'
    profile_height = 500
    plot_stacked_xrd(c, main, profiles, height=profile_height, show_angle_labels=False)
    children = [(main,profile_height,7,PLOT_TOP_MARGIN)]
    for i,color in enumerate([PALETTE[5],'#9E4B80']):
        name=c.main+f'_parent{i+1}';last=i==1
        c.xrd_strip(name,f'parent{i}_height',f'parent{i}_x',f'Parent {chr(65+i)}',color,last=last,height=35)
        children.append((name,35,52 if last else 3,3))
    c.xrd_layout(children, top=44)
    c.visual_requirements.update(panel_order=['stacked_observed_profiles','parent_A_simulation','parent_B_simulation'],
        simulation_relative_heights=True,peak_correspondence_guides=False)
    c.notes.append('合成母構造A/Bから生成したピークを重み付きで合成し、焼鈍温度ごとにパターンを変えたデモ。計算ピークはA/Bそれぞれの最大値を1として表示する。')
    cases.append(c)

    for number,slug,title,condition,unit,values in [
        (20,'xrd_temperature','XRD：温度変化の強度マップ','Temperature','K',np.linspace(300,800,51)),
        (21,'xrd_pressure','XRD：圧力変化の強度マップ','Pressure','GPa',np.linspace(0,12,61))]:
        c=Case(number,slug,title,'XRD',
            f'合成の{condition}変化XRDを、横軸2θ・縦軸{condition} / {unit}のマップにしてください。強度は低い値を青、高い値を赤とする連続カラースケールで表し、Intensity / arb. unitsと表示してください。2θは数字付き10度大目盛りと数字なし2度小目盛りにしてください。',
            '2θと条件の向き・青→赤の連続強度・条件の単位・ピーク移動と相変化')
        angle=np.linspace(10,80,1401);fraction=(values-values[0])/np.ptp(values)
        matrix=np.full((len(angle),len(values)),.012)
        matrix+=.006*(angle[:,None]-10)/70
        for j,f in enumerate(fraction):
            for p,a,s in [(21.5,.55,.14),(30.8,1.,.17),(39.2,.62,.19),(47.6,.8,.20),(58.2,.45,.22),(69.4,.3,.25)]:
                shift=(-.65*f*(p/31)) if number==20 else (1.45*f*(p/31))
                weight=1-.50/(1+np.exp(-(f-.58)/.055))
                matrix[:,j]+=a*weight*np.exp(-.5*((angle-p-shift)/(s+.065*f))**2)
            onset=.70/(1+np.exp(-(f-.58)/.045))
            for p,a in [(28.5,.75),(44.0,.60),(63.5,.48)]:
                shift=(-.40*f) if number==20 else .95*f
                matrix[:,j]+=onset*a*np.exp(-.5*((angle-p-shift)/.23)**2)
        matrix+=c.rng.normal(0,.0015,matrix.shape);matrix=np.clip(matrix,0,None)
        matrix/=matrix.max()
        # Igor waves are column-major: each CSV block is one entire 2theta scan.
        c.table({'flat_intensity':matrix.ravel(order='F')},{'flat_intensity':'arb. units'},'intensity_column_major.csv')
        c.table({'two_theta':angle,'axis_placeholder':np.zeros(len(angle))},{'two_theta':'degree'},'angle_axis.csv')
        c.table({'condition':values},{'condition':unit},'condition_axis.csv')
        path=c.w('intensity_map');c.expected_waves[path]=matrix
        c.cmd(f'Duplicate {c.w("flat_intensity")},{path}')
        c.cmd(f'Redimension/N=({len(angle)},{len(values)}) {path}')
        c.cmd(f'SetScale/P x,{angle[0]},{angle[1]-angle[0]:.17g},"degree",{path}')
        c.cmd(f'SetScale/P y,{values[0]},{values[1]-values[0]:.17g},{q(unit)},{path}')
        c.unit('intensity_map','arb. units')
        c.plot(c.main,
            'axis_placeholder','two_theta','2θ (degree)',f'{condition} / {unit}',(10,80),(float(values[0]),float(values[-1])),
            width=420,height=340,margins=(72,52,PLOT_TOP_MARGIN,110))
        c.cmd(f'RemoveFromGraph {c.w("axis_placeholder")}')
        c.expected_graphs[c.main]['traces']=[]
        c.cmd(f'AppendImage {path}')
        c.cmd(f'ModifyImage {path} ctab={{0,1,ColdWarm,0}}')
        c.cmd(f'ColorScale/N=intensity_scale/A=LC/X=106/Y=0/F=0 image={path},font="DejaVu Sans",fSize=10,width=13,heightPct=80,nticks=5,minor=0')
        c.cmd('AppendText '+q('Intensity / arb. units'))
        c.expected_graphs[c.main]['images']=[dict(wave=path,color_table='ColdWarm',color_range=[0,1],
            reverse=False,colorbar_visible=True,colorbar_label_raw='Intensity / arb. units')]
        c.xrd_axes(intensity=False)
        c.parameters=dict(matrix_shape=list(matrix.shape),csv_order='F: all 2theta points for condition[0], then condition[1], ...',
            two_theta_start=float(angle[0]),two_theta_step=float(angle[1]-angle[0]),
            condition_start=float(values[0]),condition_step=float(values[1]-values[0]),condition_unit=unit,
            normalization='one global maximum over the entire condition series; no per-scan normalization',
            color_range=[0,1],color_table='ColdWarm',peak_shift='lower angle on heating' if number==20 else 'higher angle on compression')
        c.visual_requirements=dict(x_axis='2theta',y_axis=condition.lower(),y_unit=unit,
            intensity_colorbar_label='Intensity / arb. units',continuous_colormap=True,
            low_intensity_color='blue',high_intensity_color='red',
            two_theta_major_degrees=10,two_theta_minor_degrees=2,minor_tick_numbers=False)
        c.notes.append('全て合成データ。ピーク移動と連続的な相の寄与の変化は描画評価用で、実在物質の相図や未発表測定を表さない。')
        cases.append(c)
    return cases


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def write_inputs(case,directory):
    (directory/'inputs').mkdir(parents=True,exist_ok=True)
    bindings=[]
    for table in case.inputs:
        path=directory/'inputs'/table['file']
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.writer(f);writer.writerow(table['columns'])
            arrays=list(table['arrays'].values())
            writer.writerows(zip(*arrays,strict=True))
        bindings.append(dict(file='inputs/'+table['file'],sha256=digest(path),
            first_data_row_1_based=2,columns=table['columns'],kinds=table['kinds'],row_count=len(arrays[0])))
    script=directory/'draw_commands.txt'
    script.write_text('\n'.join(case.commands)+'\n',encoding='utf-8')
    return bindings,script


def replay(directory,task):
    document=empty_document()
    document.source=replace(document.source,basename=task['id']+'.mdsg')
    allwaves=[]
    for binding in task['input_bindings']:
        path=directory/binding['file']
        assert digest(path)==binding['sha256'],'Frozen input changed'
        rows=text_rows(read_text(path),'Comma')
        assert rows[0]==binding['columns']
        allwaves.extend(import_columns(rows,1,binding['columns'],binding['kinds']))
    document.current=put_waves(document,allwaves)
    engine=CommandEngine(DocumentServices(document))
    result=engine.execute((directory/'draw_commands.txt').read_text(encoding='utf-8'))
    if not result.success:
        # Identify the failed statement without keeping any partially edited output.
        scratch=empty_document();scratch.current=put_waves(scratch,allwaves)
        probe=CommandEngine(DocumentServices(scratch))
        for number,line in enumerate((directory/'draw_commands.txt').read_text().splitlines(),1):
            step=probe.execute(line)
            if not step.success: raise RuntimeError(f'{task["id"]}: line {number}: {line}\n{step.message}')
        raise RuntimeError(result.message)
    validate_references(document,document.current)
    return document,result


def state_projection(document):
    waves=[]
    for w in document.render_source().waves:
        waves.append(dict(path=w.igor_path,dtype=w.dtype,shape=w.shape,units=w.data_units,
            scaling=w.dimension_scaling,dimension_units=w.dimension_units,
            values_sha256=hashlib.sha256(w.data.tobytes()).hexdigest()))
    return dict(graphs=[asdict(g) for g in document.current.graphs],waves=waves,layout=document.current.layout)


def verify_expected(case,document):
    source=document.render_source();checks=[]
    for binding in case.inputs:
        for name,values in binding['arrays'].items():
            actual=source.wave(name)
            assert actual is not None
            np.testing.assert_array_equal(actual.data,values)
    checks.append('Imported input values, NaN masks and row order preserved')
    for name,expected in case.expected_waves.items():
        actual=source.wave(name)
        np.testing.assert_allclose(actual.data,expected,rtol=2e-12,atol=2e-12,equal_nan=True)
        assert not actual.data.flags.writeable
    checks.append(f'{len(case.expected_waves)} scientific transforms match independent generating values')
    for name,unit in case.expected_units.items():assert source.wave(name).data_units==unit
    checks.append('Required wave units preserved')
    for name,spec in case.expected_graphs.items():
        g=document.graph(name);assert g.window_kind==spec['kind']
        assert not {'case_title', 'case_subtitle'}.intersection(a.name for a in g.annotations), name
        if spec['kind']=='Layout':
            assert [(i.graph,list(i.rect)) for i in g.layout_items]==[(i['graph'],i['rect']) for i in spec['items']]
            continue
        assert g.host==spec['host']
        assert [(t.name,t.y_wave.removeprefix('root:'),t.x_wave.removeprefix('root:')) for t in g.traces]==[(t['name'],t['y'],t['x']) for t in spec['traces']]
        if 'images' in spec:
            assert len(g.images)==len(spec['images'])
            for image,expected in zip(g.images,spec['images'],strict=True):
                actual=asdict(image);actual['wave']=actual['wave'].removeprefix('root:')
                for key,value in expected.items():
                    found=actual[key]
                    assert (list(found) if isinstance(found,tuple) else found)==value,(key,found,value)
        for name,a in spec['axes'].items():
            actual=next(axis for axis in g.axes if axis.name==name)
            assert list(actual.limits)==a['limits']
            assert actual.label_raw==a['label'],(case.id,name,actual.label_raw,a['label'])
            if 'reverse' in a: assert actual.style.reverse==a['reverse']
            for key,value in a.get('style',{}).items():
                found=getattr(actual.style,key)
                assert (list(found) if isinstance(found,tuple) else found)==value,(case.id,key,found,value)
    checks.append('Graph/trace identities, X/Y bindings, labels, ranges, inset hosts and Layout rectangles match task contract')
    checks.append('Graph titles and subtitles omitted across all panels')
    for extra in case.checks:
        values=source.wave(extra['wave']).data
        if extra['kind']=='max':np.testing.assert_allclose(np.nanmax(values),extra['expected'])
        if extra['kind']=='even':np.testing.assert_allclose(values,values[::-1],atol=2e-12)
        if extra['kind']=='odd':np.testing.assert_allclose(values,-values[::-1],atol=2e-12)
        if extra['kind']=='increasing':assert np.all(np.diff(values)>0)
        if extra['kind']=='decreasing':assert np.all(np.diff(values)<0)
    if extra_checks:=len(case.checks):checks.append(f'{extra_checks} task-specific symmetry/order/normalization checks passed')
    return checks


def verify_stacked_xrd(case, document, figure, ax, stack):
    graph = document.graph(stack['graph'])
    conditions = stack['conditions_bottom_to_top']
    assert len(graph.traces) == len(conditions)
    assert len({condition['color'] for condition in conditions}) == len(conditions)
    assert len({condition['label'] for condition in conditions}) == len(conditions)
    lines = {line.get_gid(): line for line in ax.lines}
    artists = {artist.get_gid(): artist for artist in ax.artists}
    renderer = figure.canvas.get_renderer()
    previous_top = ax.get_ylim()[0]
    for trace, condition in zip(graph.traces, conditions, strict=True):
        assert trace.name == condition['trace']
        assert trace.offset == (0, condition['y_offset'])
        line = lines[f'trace:{trace.name}']
        assert to_hex(line.get_color()) == condition['color'].lower()
        y = line.get_ydata()
        np.testing.assert_allclose(y, case.expected_waves[trace.name] + condition['y_offset'])
        assert previous_top < np.min(y) <= np.max(y) < ax.get_ylim()[1]
        previous_top = np.max(y)

    legend = artists[f'annotation:{stack["legend_annotation"]}']
    assert legend.get_visible()
    assert not {'annotation:case_title', 'annotation:case_subtitle'}.intersection(artists)
    runs = text_runs(legend.text.raw, 'DejaVu Sans', 11)
    trace_names = [condition['trace'] for condition in reversed(conditions)]
    assert [run.symbol for run in runs if run.symbol] == trace_names
    assert [(run.text.strip(), to_hex(run.color)) for run in runs if run.text.strip()] == [
        (condition['label'], condition['color'].lower()) for condition in reversed(conditions)
    ]
    assert all(legend.text.symbol_handles[name] is lines[f'trace:{name}'] for name in trace_names)
    box = legend.get_window_extent(renderer)
    plot = ax.bbox
    assert plot.x0 + plot.width/2 < box.x0 < box.x1 < plot.x1
    assert plot.y0 + plot.height/2 < box.y0 < box.y1 < plot.y1
    clearance = box.padded(renderer.points_to_pixels(1))
    for trace_name in trace_names:
        line = lines[f'trace:{trace_name}']
        trace_path = line.get_path().transformed(line.get_transform())
        assert not trace_path.intersects_bbox(clearance, filled=False)


def verify_xrd_render(case,document,figure):
    """Check the user-specified convention against rendered artists as well as state."""
    if case.domain!='XRD':return []
    axes=figure.axes[:1] if 'color_table' in case.parameters else figure.axes
    for ax in axes:
        major=ax.xaxis.get_majorticklocs();major=major[(major>=10)&(major<=80)]
        np.testing.assert_allclose(major,np.arange(10,81,10))
        minor=ax.xaxis.get_minorticklocs();minor=minor[(minor>=10)&(minor<=80)]
        np.testing.assert_allclose(minor,[x for x in range(12,80,2) if x%10])
        assert not any(t.get_visible() and t.get_text() for t in ax.xaxis.get_minorticklabels())
        if case.visual_requirements.get('intensity_y_ticks') is False:
            assert len(ax.yaxis.get_majorticklocs())==len(ax.yaxis.get_minorticklocs())==0
    messages=['Rendered 2theta major ticks are 10 degrees, minor ticks are 2 degrees without numbers']
    if case.visual_requirements.get('intensity_y_ticks') is False:
        messages.append('No rendered major/minor Y ticks on any intensity/reference/residual panel')
        assert axes[0].get_ylabel()=='Intensity / arb. units'
    if stack := case.visual_requirements.get('stacked_profiles'):
        verify_stacked_xrd(case, document, figure, axes[0], stack)
        messages.append('Three distinct, vertically offset traces and matching labels in an upper-right legend inside the plot, with no title or trace overlap')
    if 'panel_order' in case.visual_requirements:
        assert len(axes)==len(case.visual_requirements['panel_order'])
        for upper,lower in zip(axes,axes[1:]):
            assert upper.bbox.y0>lower.bbox.y1-1e-6
            np.testing.assert_allclose([upper.bbox.x0,upper.bbox.x1],[lower.bbox.x0,lower.bbox.x1],atol=1e-6)
        assert not any(g.drawings for g in document.current.graphs)
        messages.append('Requested top-to-bottom panel order and identical 2theta data-area geometry; no correspondence guide drawings')
        phase_axes=axes[1:-1] if case.id.startswith('d02_') else axes[1:]
        for graph,ax in zip([g for g in document.current.graphs if g.name in [i.graph for i in document.graph(case.main).layout_items]][1:],phase_axes):
            assert graph.traces[0].mode==1
        if case.id.startswith('d02_'):
            for i in range(3):
                np.testing.assert_array_equal(document.render_source().wave(case.w(f'phase{i}_y')).data,.8)
            messages.append('Three separate uniform-height Bragg-position rows above observed-minus-calculated residual')
            np.testing.assert_allclose(axes[0].bbox.height/np.ptp(axes[0].get_ylim()),axes[-1].bbox.height/np.ptp(axes[-1].get_ylim()))
            messages.append('Residual and observed/calculated panels use identical intensity-to-pixel scale')
        else:
            for i in range(2):assert np.ptp(document.render_source().wave(case.w(f'parent{i}_height')).data)>.2
            messages.append('Both simulation stick rows preserve their varying relative peak heights')
    if 'color_table' in case.parameters:
        ax=axes[0];image=ax.images[0];matrix=document.render_source().wave(case.w('intensity_map'))
        np.testing.assert_array_equal(np.asarray(image.get_array()),matrix.data.T)
        assert image.origin=='lower'
        assert image.norm.vmin==0 and image.norm.vmax==1
        cold,hot=image.cmap(0.),image.cmap(1.)
        assert cold[2]>cold[0] and hot[0]>hot[2] and image.cmap.N>=256
        assert len(figure.axes)==2 and figure.axes[1].get_ylabel()=='Intensity / arb. units'
        assert figure.axes[1].bbox.x0>ax.bbox.x1
        assert ax.get_ylabel()==('Temperature / K' if case.id.startswith('d20_') else 'Pressure / GPa')
        np.testing.assert_allclose(matrix.coordinate(1),case.inputs[-1]['arrays'][case.w('condition')])
        messages.append('Condition is the vertical coordinate, intensity matrix orientation is correct, and a continuous blue-to-red colorbar covers the global 0–1 scale')
    return messages


def render(document,name,dpi=130):
    g=document.graph(name);renderer=IgorMatplotlibRenderer()
    size=(8.5,11) if g.window_kind=='Layout' else renderer.export_size(g)
    figure=Figure(figsize=size,dpi=dpi);FigureCanvasAgg(figure)
    renderer.render(figure,document,name);figure.canvas.draw()
    return figure


def axis_geometry_checks(figure):
    outside=[];overlap=[];renderer=figure.canvas.get_renderer();bounds=figure.bbox
    for ax in figure.axes:
        if not ax.get_visible():continue
        for axis in [ax.xaxis,ax.yaxis]:
            if not axis.get_visible():continue
            low,high=sorted(axis.get_view_interval());ticks=[]
            for tick in axis.get_major_ticks()+axis.get_minor_ticks():
                if low-1e-8<=tick.get_loc()<=high+1e-8:
                    ticks.extend(t for t in [tick.label1,tick.label2] if t.get_visible() and t.get_text().strip())
            for text in [axis.label,*ticks]:
                if not text.get_visible() or not text.get_text().strip():continue
                box=text.get_window_extent(renderer)
                if box.width>0 and box.height>0 and (box.x0<-.5 or box.y0<-.5 or box.x1>bounds.x1+.5 or box.y1>bounds.y1+.5):outside.append(text.get_text())
            if axis.label.get_visible() and axis.label.get_text().strip():
                box=axis.label.get_window_extent(renderer)
                overlap.extend(axis.label.get_text()+' / '+t.get_text() for t in ticks if box.overlaps(t.get_window_extent(renderer)))
    return dict(axis_text_outside_canvas=sorted(set(outside)),axis_label_tick_overlap=sorted(set(overlap)))


def build(only=()):
    OUT.mkdir(parents=True,exist_ok=True)
    accepted=OUT/'accepted_baselines.json'
    if accepted.exists() and json.loads(accepted.read_text()).get('accepted'):
        raise ValueError('This directory contains adopted baselines. Use a separate --output directory.')
    cases=first_cases()+additional_cases()+xrd_condition_cases()
    records=[];documents=[]
    font_messages=[]
    class FontLog(logging.Handler):
        def emit(self,record):font_messages.append(record.getMessage())
    logger=logging.getLogger('matplotlib.font_manager');logger.handlers=[FontLog()];logger.propagate=False
    for case in cases:
        directory=OUT/'cases'/case.id;directory.mkdir(parents=True,exist_ok=True)
        if only and case.id not in only and (directory/'document.mdsg').exists():
            restored=load_graph_document(directory/'document.mdsg');verify_expected(case,restored)
            records.append(json.loads((directory/'validation.json').read_text()))
            documents.append(restored)
            continue
        bindings,script=write_inputs(case,directory)
        task=dict(format='mds-graph-drawing-task',version=1,id=case.id,title=case.title,
            domain=case.domain,user_request=case.request,scope='Graph Editor drawing and explicit data transformations',
            review_status='awaiting_user_review',main_graph=case.main,
            initial_condition='new empty Graph Editor document; all inputs bound from the supplied CSV files',
            input_bindings=bindings,physical_parameters=case.parameters,
            native_command_recipe='draw_commands.txt',native_recipe_sha256=digest(script),
            expected_graphs=case.expected_graphs,expected_units=case.expected_units,
            outputs=['figure.png','figure.svg','figure.pdf','document.mdsg','state_readback.json'],
            machine_acceptance=['input values and order preserved','explicit units and transformations correct',
                'graph titles and subtitles omitted across all panels',
                'trace and axis state matches contract','two fresh replays produce identical semantic state and pixels',
                'MDSG save/reload preserves state and pixels','invalid late command leaves the document unchanged'],
            human_acceptance=dict(status='pending',focus=case.focus,
                checks=['physical message is immediately readable','series and conditions are unambiguous',
                    'no important data/label/legend collision','scientific units and notation are appropriate',
                    'inset/panels and typography work at the intended output size'],approval_required_for_baseline_adoption=True),
            notes=case.notes)
        task['visual_requirements']={'graph_title':False, **case.visual_requirements}
        if 'stacked_profiles' in case.visual_requirements:
            task['machine_acceptance'].append('one legend inside the upper right with matching labels and clearance from every trace')
        (directory/'task.json').write_text(json.dumps(task,ensure_ascii=False,indent=2),encoding='utf-8')
        document,result=replay(directory,task);checks=verify_expected(case,document)
        second,_=replay(directory,task);verify_expected(case,second)
        assert state_projection(document)==state_projection(second)
        save_graph_document(directory/'document.mdsg',document)
        restored=load_graph_document(directory/'document.mdsg');verify_expected(case,restored)
        projection=state_projection(restored)
        assert state_projection(document)==projection
        (directory/'state_readback.json').write_text(json.dumps(projection,ensure_ascii=False,indent=2),encoding='utf-8')
        # Atomic rejection is checked against the actual current command engine.
        target=next(g for g in restored.current.graphs if g.window_kind=='Graph')
        x_wave=target.traces[0].x_wave if target.traces else case.w('two_theta')
        invalid=f'SetAxis/W={target.name} bottom -123,123\nAppendToGraph/W={target.name} {case.prefix}_does_not_exist vs {x_wave}'
        before=state_projection(restored)
        bad=CommandEngine(DocumentServices(restored)).execute(invalid)
        assert not bad.success and state_projection(restored)==before
        (directory/'invalid_command.txt').write_text(invalid+'\n')
        font_messages.clear()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            a=render(document,case.main);b=render(second,case.main);r=render(restored,case.main)
            np.testing.assert_array_equal(np.asarray(a.canvas.buffer_rgba()),np.asarray(b.canvas.buffer_rgba()))
            np.testing.assert_array_equal(np.asarray(a.canvas.buffer_rgba()),np.asarray(r.canvas.buffer_rgba()))
            geom=axis_geometry_checks(r)
            checks.extend(verify_xrd_render(case,restored,r))
            assert not geom['axis_text_outside_canvas'] and not geom['axis_label_tick_overlap'],geom
            if case.id=='d15_nyquist':
                ax=r.axes[0]
                ratio=(ax.bbox.width/np.ptp(ax.get_xlim()))/(ax.bbox.height/np.ptp(ax.get_ylim()))
                assert abs(ratio-1)<1e-10
                checks.append('Nyquist X/Y physical scale is 1:1')
            if case.id=='d13_bands_dos':
                bands,dos=r.axes
                assert abs(bands.bbox.y0-dos.bbox.y0)<1e-6
                assert abs(bands.bbox.y1-dos.bbox.y1)<1e-6
                checks.append('Band and DOS data areas share the same energy-to-pixel scale and vertical origin')
            if case.id in {'d05_mpms_mh','d06_ppms_rho_t'}:
                host=r.axes[0].bbox;child=r.subfigs[0].bbox
                assert host.contains(child.x0,child.y0) and host.contains(child.x1,child.y1)
                checks.append('Entire inset subfigure lies within the host data rectangle')
            if case.id=='d06_ppms_rho_t':
                renderer = r.canvas.get_renderer()
                geometry = next(artist for artist in r.axes[0].artists if artist.get_gid() == 'annotation:sample_geometry')
                geometry_box = geometry.get_window_extent(renderer)
                inset = r.axes[1]
                assert not geometry_box.overlaps(inset.bbox)
                for axis in (inset.xaxis, inset.yaxis):
                    for label in [axis.label, *axis.get_ticklabels()]:
                        if label.get_visible() and label.get_text():
                            assert not geometry_box.overlaps(label.get_window_extent(renderer)), label.get_text()
                checks.append('Sample geometry annotation clears the inset, including its tick labels')
            for ext in ['png','svg','pdf']:
                save_graphics(directory/f'figure.{ext}',restored,case.main,
                    GraphicsSettings(format=ext,dpi=220,size_inches=(8.5,11) if restored.graph(case.main).window_kind=='Layout' else None))
            for fig in [a,b,r]:fig.clear()
        report=restored.compatibility(case.main)
        record=dict(id=case.id,title=case.title,domain=case.domain,request=case.request,focus=case.focus,
            checks=checks,fresh_replay_state_identical=True,fresh_replay_pixels_identical=True,
            save_reload_state_identical=True,save_reload_pixels_identical=True,
            invalid_command_rejected=True,invalid_command_rollback=True,invalid_command_message=bad.message,
            native_status=result.status,native_warnings=result.warnings,diagnostics=[asdict(d) for d in report.diagnostics],
            render_warnings=sorted({str(w.message) for w in caught}),font_messages=sorted(set(font_messages)),
            human_review='pending',**geom)
        (directory/'validation.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        np.savez_compressed(directory/'independent_transform_reference.npz',**case.expected_waves)
        records.append(record);documents.append(restored)
        print(case.id,'replay/save/rollback PASS','outside=',len(geom['axis_text_outside_canvas']),'overlap=',len(geom['axis_label_tick_overlap']),flush=True)
    combined=empty_document();combined.source=replace(combined.source,basename='solid_state_drawing_tasks.mdsg')
    combined.current.waves=tuple(w for d in documents for w in d.render_source().waves)
    combined.current.graphs=tuple(g for d in documents for g in d.current.graphs)
    combined.current.layout={key:value for d in documents for key,value in d.current.layout.items()}
    validate_references(combined,combined.current)
    save_graph_document(OUT/'all_domain_examples.mdsg',combined)
    meta=dict(format='solid-state-graph-baseline-candidates',version=2,review_status='awaiting_user_review',
        application_version=__version__,
        graph_titles=False,
        xrd_convention_revision='2026-11-18 annealing stacks with legends inside the upper right, simulation rows, ticks and intensity-map directions',
        seed=SEED,task_count=len(records),scope='Graph Editor; prepared scientific data; no instrument-module ingestion or model selection',
        method='CSV import via graph_waves.import_columns; all graph edits via CommandEngine; native renderer/exporter; no plot post-processing',
        actual_MCP_server_implemented=False,actual_skills_implemented=False,
        wave_count=len(combined.render_source().waves),graph_count=len(combined.current.graphs),cases=records)
    (OUT/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    pdf_builder = BASE/'build_review_pdf.py'
    if not pdf_builder.is_file():
        pdf_builder = BASE.parents[1]/'build_review_pdf.py'
    subprocess.run([sys.executable,str(pdf_builder),'--suite','solid-state-v2','--directory',str(OUT)],check=True)
    write_review(cases,meta,pdf_builder)


def write_review(cases,meta,pdf_builder):
    contact_sheets(meta['cases'])
    contract='''# MCP / skills用の基準候補としての使い方

## 評価単位

評価単位は1件の「利用者の作図依頼」です。Graph Editorで、固定入力から意味の通る完成図と再編集可能な文書を得るタスクを18件用意しました。
XRD/MPMS/PPMS各解析モジュールでの装置ファイル読み込み・物性モデル推定・構造解析は別の評価範囲です。

1. `task.json` の依頼・入力の列対応・単位・物理パラメータを読む。
2. CSVを読み込み、明示された換算・表示変換を実行する。
3. trace、軸、凡例、注記、insetまたはLayoutを作る。
4. 数値配列と図の状態を読み返し、依頼との対応を確認する。
5. PNG/SVG/PDFとMDSGを保存する。
6. 完成図を人が評価し、採用する作例を決める。

`draw_commands.txt` は現在のGraph EditorのCommandEngineで再実行した具体的なレシピです。将来のMCP APIが別のtool分割を採用しても、task.jsonが示す入力・意味・出力状態を比較できます。
`state_readback.json` は現在の図の状態をGUI座標やOSのクリック位置に依存せず読み出した記録です。

## 現在実行した機械検査

|検査|対象|
|---|---|
|固定入力のSHA-256|各CSVと作図コマンド|
|入力の保持|配列値・NaN位置・行順序|
|物理量の換算|独立に計算した期待値、明示した単位|
|図の状態|trace名、X/Y対応、軸ラベル・範囲・反転、insetのhost、Layout矩形|
|同じ初期条件からの再実行|空文書から2回実行した状態と描画|
|文書の再現性|MDSG保存・再読込の状態と描画|
|失敗の原子性|有効な軸変更の後に存在しないwave参照を置き、変更全体が戻ること|
|幾何条件|inset全体が親のデータ領域内にあること、Band/DOSの共通エネルギー縮尺、Nyquistの等縮尺|
|文字の一部の検査|軸文字のcanvas外へのはみ出し、軸ラベルと同じ軸の目盛文字の接触|

描画の画素一致は同一Linux環境・同一の版・同一のフォントとライブラリでの再実行検査です。別のOSや描画ライブラリの変更を評価するときは、物理的・意味的な検査と採用済みの完成図に対する目視評価を併用します。
凡例とデータの干渉、科学的な説明の分かりやすさ、印刷時の可読性等は人の採用判定に含めます。
すべての作例で図中のタイトルと副題を省きます。測定条件や誤差棒の意味は、凡例と注記で示します。

## 将来のMCP側で満たすべき契約

以下は今後の実装要件です。今回の結果を、未実装のMCPサーバーを検証済みと解釈しないでください。

- 文書・wave・graph・traceを安定した識別子で選択し、現在状態を取得できる。
- 列の意味、単位、質量、式量、試料形状、誤差の意味、±Hの対応等が不足する場合、必要な情報を返せる。
- 不正な長さ・不正な物理パラメータを構造化したエラーで通知し、文書を途中まで変更しない。
- 作図をまとめて確定し、失敗時の結果と変更対象を機械可読な形で返せる。
- 同じ要求の再送による二重作成を防ぐ仕組み、または作成と更新の明確な区別を持つ。
- コマンド履歴の文章だけに依存せず、実データと意味的な図の状態を保存する。
- 出力ファイル、図のサイズ、表示する量・単位、互換範囲の診断を取得できる。

今回のレシピは「新規の空文書」を初期条件にしています。同じ既存文書への再送時のidempotency、MCPのtool schema、transport、権限境界、skillsの指示追従は将来の実装評価で追加します。

## skills側で評価すること

- 利用者の科学的な意図を、必要な変換・軸・系列・完成図に正しく対応付ける。
- 単位、参照値、質量・式量・形状を根拠なく補わない。
- 指定済みのCurie–Weiss、Arrhenius、VRH、直接遷移の仮定を保持する。
- 提示済みのモデル曲線を追加fitの結果と取り違えない。
- 元データを保持し、変換後の量・誤差・符号・行順序を検査する。
- 図を保存する前に、系列と条件、科学記号、凡例、余白、inset、複数図の対応を確認する。
- 条件を満たせない場合は、作成前に不足内容や未対応機能を具体的に伝える。

## 採用手順

この18件はすべて `awaiting_user_review` です。利用者が見た目と意味を確認して採用したIDだけを `accepted_baselines.json` のacceptedへ記録します。
採用後は入力CSV、task.json、独立した期待値、レシピ、完成図と環境情報をまとめて固定します。将来の改版結果は新しい出力先に作り、基準そのものの更新は利用者の判断として扱います。
'''
    contract=contract.replace('18件',f'{len(cases)}件')
    contract+='''
## XRDの指定書式（2026-11-18更新）

- 通常の強度図は縦目盛りなし、ラベルは `Intensity / arb. units`。
- 2θは数字付き10°大目盛り、数字なし2°小目盛り。
- 通常XRDと母構造比較は、焼鈍温度700・800・900 Kの曲線を下から順に縦へずらす。グラフタイトルは省き、条件の凡例は描画範囲内の右上で曲線に重ならない位置にまとめる。
- 母構造比較は実験パターンの下に、相対強度付きのsimピークを母構造ごとに別段で置く。実験とsimを結ぶ垂直線は省く。
- リートベルト形式は観測＋計算、相別Bragg位置、観測−計算の残差の順。今回は3相の合成曲線を表示する作図タスク。
- 条件変化XRDは横2θ・縦温度または圧力・青（弱）→赤（強）の連続強度。条件軸の数値と単位は残す。
- 全て新規の合成データ。参考画像や未発表データは入力・出力・リポジトリに含めない。

`visual_requirements` と `expected_graphs` にこれらを記録する。縦オフセット、曲線と凡例の色と対応、凡例の位置と曲線との間隔、目盛り、段の順序、共通X座標、行列の向き、カラーマップの両端を検査する。
'''
    (OUT/'MCP_SKILLS_BASELINE.md').write_text(contract,encoding='utf-8')
    acceptance=OUT/'accepted_baselines.json'
    status=json.loads(acceptance.read_text()) if acceptance.exists() else dict(status='awaiting_user_review',accepted=[])
    status['candidates']=[c.id for c in cases]
    acceptance.write_text(json.dumps(status,ensure_ascii=False,indent=2))
    review=OUT/'human_review.csv';previous={}
    if review.exists():
        with review.open(encoding='utf-8-sig',newline='') as f:
            previous={row[0]:row for row in list(csv.reader(f))[1:]}
    with (OUT/'human_review.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['id','作図タスク','入力・物理量の意味','図の読みやすさ','凡例・注記・余白','基準への採用判断','コメント'])
        writer.writerows([c.id,c.title,*previous.get(c.id,['']*7)[2:]] for c in cases)
    with (OUT/'task_catalog.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['id','domain','title','user_request','human_focus','machine_checks','human_review'])
        writer.writerows([c.id,c.domain,c.title,c.request,c.focus,'PASS','pending'] for c in cases)
    rows='\n'.join(f'|{c.id}|{c.title}|{c.focus}|' for c in cases)
    readme=f'''# 固体科学の作図タスク：基準候補 v2

Graph EditorのMCPサーバー化・skills化へ向けて、**18件の作図タスク**を作成しました。
v{meta['application_version']} を使用。対象はGraph Editorの作図と明示されたデータ変換です。

## 最初に見るもの

- `gallery.html`：自然文の作図依頼と完成図を対応させた一覧。
- `all_domain_figures.pdf`：各ページに作例名と、作例へ移動できるしおりを付けた全18作例の一覧PDF。
- `all_domain_examples.mdsg`：全作例を開けるGraph Editor文書（{meta['graph_count']} graph、{meta['wave_count']} waves）。
- `human_review.csv`：利用者の採用判定欄。全件未記入。
- `MCP_SKILLS_BASELINE.md`：機械検査、人の評価、今後のMCP/skills実装で追加すべき契約。
- `cases/<id>/`：固定CSV、task.json、作図コマンド、独立した変換期待値、図、MDSG、状態readback、検査結果。
- `reproducibility/`：生成・再実行スクリプトと固定依存関係。

## 今回の結果

全18件で、入力の保持、単位と変換値、軸とtraceの状態、空文書からの2回再実行、保存・再読込、失敗時のrollbackを確認しました。
画素比較は同じLinux環境におけるnative描画同士の検査です。見た目の基準として採用するかは利用者の判定を待ちます。
Nyquistは1 Ωの長さがX・Yで一致し、Band/DOSはエネルギーの原点と縮尺が一致することを追加検査しました。2件のinsetは親のデータ領域内に収まることを検査しました。

データはすべて合成、seedは{SEED}＋作例番号です。モデル線・参照ピーク・バンド・DOS等は提示済みの固定入力です。各解析モジュールでの装置ファイル読込・物性モデル推定・構造解析は別の評価範囲です。
Graph Editorへの読み込みには既存のCSV import処理を使い、図の作成・変更は既存のCommandEngine経由で実行しました。
アプリの描画処理はそのまま使用しています。個別のPNG/SVG/PDFに描画後の加工は加えていません。
全作例で図中のタイトルと副題を省いています。
一覧PDFの作例名は、個別PDFを組み合わせる段階で図の外に追加しています。

## 作図タスク

|ID|タスク|人が見る主な点|
|---|---|---|
{rows}

## 再実行

同じ版のリポジトリで `uv sync --frozen` を実行し、DejaVu Sansを利用できる環境で次を実行します。

```sh
QT_QPA_PLATFORM=offscreen MPLCONFIGDIR=/tmp/graph-baseline-mpl .venv/bin/python /path/to/reproducibility/replay_domain_case.py --case /path/to/cases/d15_nyquist --output /path/to/new-result
```

レシピは新規の空文書から実行します。実行済みの文書へそのまま再送する仕様ではありません。
前回の23作例は探索用として別フォルダーに保持しました。今回の18件を、入力・操作・期待状態・完成図が揃った採用候補として追加しています。
'''
    readme=readme.replace('18件',f'{len(cases)}件').replace('18作例',f'{len(cases)}作例')
    readme+='\n通常XRD（d01）と母構造比較（d19）は、3つの焼鈍温度を色分けして縦に重ねます。グラフタイトルを省き、描画範囲内の右上に凡例を置きます。d19では実験パターンの下に母構造のsimピークを置きます。XRDの指定書式は `MCP_SKILLS_BASELINE.md` に記録しています。\n'
    (OUT/'README_ja.md').write_text(readme,encoding='utf-8')
    cards=[]
    for case,record in zip(cases,meta['cases'],strict=True):
        prefix='cases/'+case.id+'/'
        image=base64.b64encode((OUT/prefix/'figure.png').read_bytes()).decode()
        filelinks=' · '.join(f'<a href="{prefix}inputs/{t["file"]}" download>{html.escape(t["file"])}</a>' for t in case.inputs)
        cards.append(f'''<article id="{case.id}"><div class="casehead"><span>{case.id} · {case.domain}</span><h2>{html.escape(case.title)}</h2><p class="status">機械検査済み · 人の採用判定待ち</p></div><div class="request"><b>利用者の作図依頼</b><p>{html.escape(case.request)}</p></div><a href="{prefix}figure.png" target="_blank"><img src="data:image/png;base64,{image}" alt="{html.escape(case.title)}" loading="lazy"></a><div class="details"><p><b>見るポイント：</b>{html.escape(case.focus)}</p><p>固定入力：{filelinks}</p><p><a href="{prefix}figure.pdf" target="_blank">PDF</a> · <a href="{prefix}figure.svg" download>SVG</a> · <a href="{prefix}document.mdsg" download>編集用MDSG</a> · <a href="{prefix}task.json" target="_blank">入力・期待状態</a> · <a href="{prefix}validation.json" target="_blank">機械検査</a></p><details><summary>再実行できる作図レシピ</summary><pre>{html.escape(chr(10).join(case.commands))}</pre><a href="{prefix}draw_commands.txt" download>コマンドを保存</a></details></div></article>''')
    nav=' '.join(f'<a href="#{c.id}">{c.id[:3]} {html.escape(c.title.split("：")[0])}</a>' for c in cases)
    gallery=f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>固体科学の作図タスク · 基準候補18件</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f0f3f6;color:#25374b;font:15px/1.7 system-ui,sans-serif}}header{{background:#18334c;color:white;padding:36px max(24px,calc((100vw - 1200px)/2))}}header h1{{font-size:29px;margin:8px 0}}header p{{color:#d1e0ed;margin:9px 0}}a{{color:#086695}}.button{{display:inline-block;background:white;border:1px solid #c7d6e0;padding:9px 16px;border-radius:6px;color:#164b71;text-decoration:none;margin:8px 8px 5px 0}}main{{max-width:1240px;margin:auto;padding:22px}}.intro,article{{background:white;border:1px solid #d7e1e9;border-radius:10px;margin:20px 0;overflow:hidden}}.intro{{padding:22px}}nav{{display:flex;flex-wrap:wrap;gap:8px}}nav a{{display:inline-block;padding:5px 10px;background:white;border:1px solid #d6e1e8;border-radius:5px;text-decoration:none;font-size:13px}}.casehead{{padding:22px 25px 3px}}.casehead span{{font-size:12px;color:#5d7a91}}h2{{font-size:23px;margin:4px 0}}.status{{font-size:13px;color:#1d755e;margin:6px 0}}.request{{padding:15px 24px;background:#f1f6fa;border-top:1px solid #e0e9f0;border-bottom:1px solid #e0e9f0}}.request p{{margin:5px 0}}article img{{display:block;max-width:100%;max-height:850px;object-fit:contain;margin:auto}}.details{{padding:4px 25px 25px}}details{{border-top:1px solid #e2e9ee;padding-top:13px}}summary{{cursor:pointer;font-weight:600}}pre{{white-space:pre-wrap;word-break:break-all;background:#eff4f8;padding:14px;max-height:400px;overflow:auto;font-size:12px}}footer{{text-align:center;color:#61798e;padding:30px}}@media(max-width:700px){{main{{padding:10px}}header h1{{font-size:23px}}h2{{font-size:20px}}}}@media print{{nav,details,.button{{display:none}}article{{break-after:page;border:0}}body{{background:white}}header{{color:black;background:white}}}}
</style><header><div>GRAPH EDITOR · SOLID-STATE SCIENCE · BASELINE CANDIDATES</div><h1>固体科学の「作図依頼」を基準にする</h1><p>18タスク · XRD / MPMS / PPMS と固体科学の代表図 · v{meta['application_version']}</p><p>固定入力 → 作図レシピ → 期待状態 → 完成図。採用する作例はご自身で判断してください。</p><a class="button" href="all_domain_figures.pdf" target="_blank">全18図のPDF</a><a class="button" href="all_domain_examples.mdsg" download>全図の編集文書</a></header><main><section class="intro"><p><b>前回の機能別作例に、利用者の科学的な作図依頼と機械検査を対応させた基準候補を追加しました。</b></p><p>18件すべてで、単位・換算・軸と系列の対応、2回の再実行、保存・再読込、失敗時のrollbackを検査済みです。見た目の採用判定は未記入にしてあります。</p><p><a href="MCP_SKILLS_BASELINE.md" download>MCP・skillsの評価契約</a> · <a href="human_review.csv" download>採用判定CSV</a> · <a href="task_catalog.csv" download>タスク一覧</a> · <a href="README_ja.md" download>説明と再実行方法</a></p><p>Graph Editorの作図が対象です。モデル線は固定入力として扱い、各解析モジュールでの装置ファイル読み込みやモデル推定は別の評価範囲にしています。</p></section><nav>{nav}</nav>{''.join(cards)}</main><footer>合成データ · 現在は全件が採用判定待ち · 個別図はnative描画のまま保存</footer></html>'''
    gallery=gallery.replace('18件',f'{len(cases)}件').replace('18タスク',f'{len(cases)}タスク').replace('18図',f'{len(cases)}図')
    (OUT/'gallery.html').write_text(gallery,encoding='utf-8')
    repro=OUT/'reproducibility';repro.mkdir(exist_ok=True)
    for source in [Path(__file__),BASE/'replay_domain_case.py',pdf_builder]:
        target=repro/source.name
        if source.resolve()!=target.resolve():shutil.copy2(source,target)
    (repro/'environment.json').write_text(json.dumps(dict(python=platform.python_version(),platform=platform.platform(),
        packages={name:importlib.metadata.version(name) for name in ['materials-data-studio','numpy','scipy','matplotlib','PySide6-Essentials']},
        application_version=meta['application_version'],fonts=['DejaVu Sans'],scope=meta['scope']),ensure_ascii=False,indent=2))
    files=sorted(p for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in {'SHA256SUMS.txt','solid-state-graph-baseline-v2.zip'})
    (OUT/'SHA256SUMS.txt').write_text('\n'.join(digest(p)+'  '+str(p.relative_to(OUT)) for p in files)+'\n')
    bundle=OUT/'solid-state-graph-baseline-v2.zip'
    with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in sorted(OUT.rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p!=bundle:archive.write(p,arcname=str(Path('solid-state-graph-baseline-v2')/p.relative_to(OUT)))
    with zipfile.ZipFile(bundle) as archive:assert archive.testzip() is None
    print('Packaged',len(cases),'drawing tasks; human approval pending;',round(bundle.stat().st_size/1e6,2),'MB ZIP',flush=True)


def contact_sheets(records):
    font = ImageFont.truetype(findfont(FontProperties(family='Noto Sans CJK JP'), fallback_to_default=False), 18)
    for page,start in enumerate(range(0,len(records),6),1):
        page_records = records[start:start+6]
        row_count = (len(page_records)+1)//2
        sheet=Image.new('RGB',(1720,30+485*row_count),'#EDF1F5');draw=ImageDraw.Draw(sheet)
        for i,record in enumerate(page_records):
            row,col=divmod(i,2);x=25+850*col;y=25+485*row
            draw.rounded_rectangle((x,y,x+825,y+465),10,fill='white')
            im=Image.open(OUT/'cases'/record['id']/'figure.png').convert('RGB');im.thumbnail((800,415))
            sheet.paste(im,(x+(825-im.width)//2,y+8))
            draw.text((x+16,y+433),record['title'],font=font,fill='#24374D')
        sheet.save(OUT/f'contact_sheet_{page}.png')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path)
    parser.add_argument('--cases',nargs='*',default=[],help='Rebuild only these candidates; preserve the other saved cases and review fields')
    args=parser.parse_args()
    if args.output:OUT=args.output.resolve()
    build(only=args.cases)
