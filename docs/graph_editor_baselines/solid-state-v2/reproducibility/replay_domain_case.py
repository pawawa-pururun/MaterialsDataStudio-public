"""Replay one frozen scientific drawing task without regenerating its inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from build_domain_baseline import replay, state_projection
from PIL import Image

from materials_data_studio.tools.command_engine import CommandEngine
from materials_data_studio.tools.command_services import DocumentServices
from materials_data_studio.tools.graph_document import load_graph_document, save_graph_document
from materials_data_studio.tools.graph_export import GraphicsSettings, save_graphics


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--case',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    case = args.case.resolve()
    out = args.output.resolve()
    if out == case or case in out.parents:
        raise ValueError('Choose a separate output directory to preserve the frozen task.')
    task=json.loads((case/'task.json').read_text())
    document,result=replay(case,task)
    reference=json.loads((case/'state_readback.json').read_text())
    assert canonical(state_projection(document))==canonical(reference),'Semantic state differs from the frozen candidate'
    with np.load(case/'independent_transform_reference.npz',allow_pickle=False) as expected:
        for name in expected.files:
            np.testing.assert_allclose(document.render_source().wave(name).data,expected[name],rtol=2e-12,atol=2e-12,equal_nan=True)
    before=canonical(state_projection(document))
    failed=CommandEngine(DocumentServices(document)).execute((case/'invalid_command.txt').read_text())
    assert not failed.success and canonical(state_projection(document))==before
    out.mkdir(parents=True,exist_ok=True)
    save_graph_document(out/'document.mdsg',document)
    restored=load_graph_document(out/'document.mdsg')
    assert canonical(state_projection(restored))==canonical(reference)
    for ext in ['png','svg','pdf']:
        save_graphics(out/f'figure.{ext}',restored,task['main_graph'],
            GraphicsSettings(format=ext,dpi=220,size_inches=(8.5,11) if restored.graph(task['main_graph']).window_kind=='Layout' else None))
    with Image.open(case/'figure.png') as a,Image.open(out/'figure.png') as b:
        pixels_same=np.array_equal(np.asarray(a),np.asarray(b))
    report=dict(id=task['id'],frozen_input_replay=True,semantic_state_matches=True,
        scientific_transforms_match=True,invalid_command_rolls_back=True,save_reload_matches=True,
        same_environment_candidate_png_pixels_equal=pixels_same,
        native_command_status=result.status,native_warnings=result.warnings,
        human_acceptance='pending; this run does not adopt the candidate as a baseline')
    (out/'replay_validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
