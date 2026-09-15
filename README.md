# Posicionamento na Tabela Salarial

Mapa de dispersão pessoa a pessoa: compara o salário de cada colaborador ativo
com a referência de mercado (Carreira Muller) do cargo equivalente. Painel
**interno, com login** — diferente do Headcount público, aqui cada bolinha é
uma pessoa e o salário aparece nominalmente, então o acesso é restrito.

## Rodar localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Contrato Neon

Mesmo projeto Neon do painel Headcount (Desenvolvimento Organizacional/Headcount
Total — "Central de Gente & Dados"). Este painel lê direto do schema `interno`
(mesmo mirror de PII do Databricks que already alimenta aquele painel):

| Tabela | Conteúdo | Alimentada por |
| --- | --- | --- |
| `interno.fato_funcionario_ativo` | Salário, cargo, diretoria/área por colaborador ativo | `etl/mirror_fatos_to_neon.py` do painel Headcount (não duplicado aqui) |
| `interno.mercado_salarial_muller` | Referência de mercado (cargo x recorte de pesquisa) | `etl/upload_faixas_salariais.py` (este projeto) |

### `.streamlit/secrets.toml`

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
```

```toml
[neon]
database_url = "postgresql://user:password@host/dbname?sslmode=require"
```

## Deploy no Streamlit Community Cloud

`secrets.toml` fica no `.gitignore` de propósito — nunca é enviado pro GitHub.
Isso significa que o login (que lê `st.secrets["neon"]["database_url"]`) **não
funciona sozinho** assim que o app é publicado: é preciso repetir o mesmo
conteúdo do `[neon]` acima em **App settings → Secrets**, no painel do
Streamlit Community Cloud, colando o mesmo bloco TOML (com a `database_url`
real, não o placeholder). Sem esse passo, a tela de login trava com "erro
temporário de conexão" — não é um bug do app, é secret faltando no deploy.

## Pipeline de referência salarial (`etl/upload_faixas_salariais.py`)

A fonte é um export manual consolidado dos 5 recortes de pesquisa de mercado
Carreira Muller (`.Assets/Faixas Salariais Carreira Muller/Filtros Carreira/*.xlsx`
— arquivos "somente na nuvem" no OneDrive, não lidos direto). O consolidado
(`etl/data/base_mercado_carreira_muller_consolidado.csv`, gitignored) tem uma
linha por (cargo, recorte de pesquisa) com o "salário adequado" de cada um.

```powershell
python etl/upload_faixas_salariais.py
```

Reexecute sempre que a pesquisa de mercado for atualizada (o script faz
truncate + reload completo — não acumula histórico, só a foto mais recente).

## Login e acesso

Mesmo fluxo de login por e-mail/senha do painel Headcount (`auth.py`) e, desde
2026-09-15, a **mesma tabela** `app_users` — mesma senha em todos os
dashboards. Até essa data era uma tabela própria (`posicionamento_app_users`),
separada porque este painel expõe salário nominal por pessoa; a unificação
foi um pedido explícito do usuário, com segregação de acesso por painel
prevista pra uma etapa futura (ainda não implementada) — hoje, quem tem
login em qualquer app do usuário entra aqui também.

```powershell
python scripts/grant_access.py
```

## Metodologia do mapa de dispersão

- Eixo X: salário mensal (R$).
- Eixo Y: % do salário adequado de mercado (100% = valor de referência do
  cargo no recorte de pesquisa selecionado), eixo fixo entre 60% e 140%.
- Linhas verdes em 80% e 120% marcam a faixa ideal de aderência; linha
  tracejada cinza em 100% marca o adequado.
- O cruzamento pessoa → referência é por nome do cargo interno
  (`descricao_cargo` contra `Cargo_Empresa` da pesquisa) — cobre ~86% dos
  colaboradores ativos (o resto, majoritariamente diretoria e cargos muito
  recentes, não tem equivalente na pesquisa e fica fora do gráfico).
- A barra lateral deixa trocar o recorte de pesquisa (5 opções) e filtrar por
  diretoria, área, categoria de atribuição e função de cargo.
