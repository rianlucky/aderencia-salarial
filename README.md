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

`etl/data/` (o consolidado de mercado e os 2 JSONs de mapeamento
diretoria/área) também é gitignored, mas por um motivo diferente: são dados
internos de RH, não segredo de acesso. O app **não quebra** sem eles (cai em
"Não informado" pra Diretoria/Área), mas pra ter a correção completa também
no deploy, cole o conteúdo de `cc_mapping.json`/`special_mappings.json` na
seção `[mapping_diretoria]` do Secrets — formato em
`.streamlit/secrets.toml.example`.

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
controlada pela **matriz de acessos** da Central (painel liberado por grupo/pessoa,
em `acesso.v_permissoes`). Cadastro de usuários e acessos pela ferramenta local
`_neon/acessos/admin_acessos.py`. O e-mail para pedir acesso vem dos Secrets
(`[app] email_suporte`).

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

## Polimento de 29/09/2026 (padrão da Central)

Página única em seções numeradas (na impressão, cada seção numa folha; a primeira folha é a capa):

1. **Posicionamento na tabela salarial** — compa-ratio pessoa a pessoa (salário ÷ salário adequado da
   pesquisa), faixa ideal 80%–120%, filtro de classificação ao lado do título.
2. **Onde está a defasagem** — aderência por nível de gerenciamento (variações juntas, como no
   Headcount) e mapa de calor diretoria × nível (% dentro da faixa).
3. **Penetração na faixa e tempo de casa** — onde o salário cai entre o mínimo e o máximo de mercado
   do cargo; compa-ratio mediano por tempo de casa.
4. **Custo de enquadramento** — quanto falta, por mês e por ano (12 + 13º + 1/3 de férias, sem
   encargos), para levar a 80% ou a 100% do adequado quem está abaixo; por diretoria e por cargo;
   lista exportável.
5. **Compressão salarial** — no mesmo cargo, mediana de quem entrou nos últimos 12 meses x veteranos.
6. **Extremos e detalhamento** — 5 mais abaixo/acima e a busca pessoa a pessoa (exportável).
7. **Job Matching** — cobertura da pesquisa e cargos com/sem equivalente.

Também: login e barra lateral padrão (rodapé com Fonte, Atualizado em e data do mercado), cabeçalho
com selos (base de pesquisa e filtros), cards com o recorte da bandeira, fonte Nunito, filtros novos
de centro de custo e nível de gerenciamento, exportações em Excel com aba "Filtros". Cálculos em
`metricas.py`. Compa-ratio interno (contra uma tabela salarial oficial) fica para quando a tabela
existir no Neon — a "faixa interna" do Job Matching é o menor e o maior salário pago hoje.

Ajustes do mesmo dia:
- **Compa-ratio e penetração em razão** (compa = salário ÷ adequado, 1,00 = na referência; penetração
  0,00 no mínimo e 1,00 no máximo de mercado); faixa ideal 0,80 a 1,20. Um "i" (desenhado em CSS) no
  card do compa-ratio e nos de custo explica os conceitos. Enquadramento com alvo em compa-ratio 0,80
  ou 1,00, com aviso de que o custo é referência para orçamento — a diretoria pode seguir uma linha
  interna própria, inclusive abaixo do mercado.
- **3 páginas na barra lateral** (`st.navigation`, como no Turnover Comercial; cada página só desenha o
  que é dela): **Analítico** (página inicial: dispersão pessoa a pessoa, extremos e detalhamento com as
  200 primeiras linhas + busca; o Excel leva todas) · **Defasagem e Enquadramento** (cards, nível e
  diretoria × nível, penetração e tempo de casa, custo de enquadramento) · **Cargo e Mercado** (Job
  Matching e compressão salarial). A classificação (Abaixo/Dentro/Acima) filtra só o Analítico. As
  planilhas Excel são geradas só no clique de exportar (antes, a cada interação).
- **Base "Personalizado (em cascata)"** (padrão): o usuário arrasta a ordem das bases; cada cargo usa a
  primeira base da lista que tem referência para ele (padrão: GRH ECI Ramo Econômico → GRH ECI Acima
  de 1000 → Indústria da Construção). A base usada aparece no tooltip, no detalhamento, no Job Matching
  e nas exportações. Componente de arrastar: `streamlit-sortables`. Em 29/09/2026 a Indústria da
  Construção cobre os 231 cargos mapeados: como fecha a lista, nenhum cargo fica sem referência pela ordem.
