"""Resolução de diretoria/área — cópia deliberada da lógica do painel Headcount
(`.../Desenvolvimento Organizacional/Headcount Total/etl/mapping.py`,
função `resolve_diretoria_area`).

`interno.fato_funcionario_ativo` é um mirror bruto de `rh.gold.fato_funcionario_ativo`
(Databricks): `nome_diretoria`/`nome_area` vêm direto do gold, sem a correção
manual por centro de custo que o Headcount aplica (o gold fica desatualizado
depois de reorganizações). Este painel tem `centro_de_custo`, `descricao_posicao`
e `id_funcionario` disponíveis na mesma tabela — dá pra aplicar a mesma
correção aqui sem duplicar pipeline nenhum, só reaproveitando os 2 JSONs de
mapeamento (`etl/data/cc_mapping.json`, `etl/data/special_mappings.json`,
cópias literais dos do Headcount, gitignored).

Se o Headcount atualizar o mapeamento (novo CC, reorganização), estes 2 JSONs
precisam ser resincronizados manualmente — mesmo trade-off que já existe pro
CSV de referência de mercado (`etl/upload_faixas_salariais.py`).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "data"

NAO_INFORMADO = "Não informado"

CC_MAPPING = json.loads((ROOT / "cc_mapping.json").read_text(encoding="utf-8"))
SPECIAL_MAPPINGS = json.loads((ROOT / "special_mappings.json").read_text(encoding="utf-8"))


def resolve_diretoria_area(cc: str | None, descricao_posicao: str | None, id_funcionario) -> tuple[str, str]:
    """Resolve diretoria/área de uma pessoa: SPECIAL_MAPPINGS (por pessoa, depois por
    cargo) tem prioridade sobre o default do CC_MAPPING. Sem entrada em nenhum dos
    dois, cai em NAO_INFORMADO (nunca quebra por CC novo/desconhecido)."""
    special = SPECIAL_MAPPINGS.get(cc) if cc is not None else None
    if special:
        by_person = special.get("by_person", {}).get(str(id_funcionario))
        if by_person:
            return by_person["diretoria"], by_person["area"]
        position = (descricao_posicao or "").rsplit(" - ", 1)[0].strip()
        by_position = special.get("by_position", {}).get(position)
        if by_position:
            return by_position["diretoria"], by_position["area"]
    default = CC_MAPPING.get(cc) if cc is not None else None
    if isinstance(default, dict):
        return default["diretoria"], default["area"]
    return NAO_INFORMADO, NAO_INFORMADO
