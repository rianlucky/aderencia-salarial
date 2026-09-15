# Contexto do produto

## Objetivo

Mapa de dispersão salarial pessoa a pessoa: onde cada colaborador está
posicionado em relação à faixa salarial de mercado (Carreira Muller) do cargo
equivalente. Ferramenta de trabalho para o time de Remuneração, não um painel
público — expõe salário nominal por pessoa.

## Estética e padrões reaproveitados do Headcount

Mesmo projeto Neon, mesmo tema navy (#064D66), mesmo cartão de login dividido,
mesmo card de KPI Vega-Lite (ribbon navy + faixa dourada) do painel Headcount
(`.../Desenvolvimento Organizacional/Headcount Total`) — decisão do usuário em
2026-09-14: "siga a estética e filtros do dashboard de Headcount".

**Acesso deliberadamente separado:** apesar de reaproveitar o mesmo Neon e o
mesmo mecanismo de login (bcrypt + tabela de usuários), a tabela de usuários é
própria (`posicionamento_app_users`, não `app_users`) — este painel mostra
salário nominal por pessoa, o Headcount só agregado, então quem tem acesso a
um não pode herdar acesso ao outro automaticamente.

## Fontes de dado

- **Salário pessoa a pessoa:** `interno.fato_funcionario_ativo` no Neon —
  mirror já existente do Databricks, alimentado pelo pipeline do painel
  Headcount (`etl/mirror_fatos_to_neon.py` daquele projeto). Este projeto não
  duplica esse pipeline, só lê a tabela.
- **Referência de mercado:** consolidado Carreira Muller, subido por
  `etl/upload_faixas_salariais.py` (este projeto) pra `interno.mercado_salarial_muller`.

## Decisão: fonte da referência de mercado é um CSV consolidado, não os xlsx originais (2026-09-14)

Os 5 recortes de pesquisa (`.Assets/Faixas Salariais Carreira Muller/Filtros
Carreira/*.xlsx`) ficaram "somente na nuvem" no OneDrive (placeholders,
`FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`) e a leitura direto por essa sessão
falhou (`OSError: Invalid argument` / `Permission denied`) mesmo depois do
usuário tentar abrir os arquivos — hidratação não completou na sessão. O
usuário já tinha um export consolidado pronto em
`C:\Users\...\Downloads\base_mercado_carreira_muller_consolidado.csv`
(5.860 linhas = 1.172 combinações cargo×pessoa × 5 recortes), que foi copiado
pra `etl/data/` (gitignored — dado de pesquisa de mercado, não é código) e
virou a fonte real do pipeline.

Estrutura do CSV: `Cargo_Empresa` (cargo interno), `Cargo_Pesquisa` (cargo
equivalente na pesquisa), `Total_Dinheiro_Adequado` (valor de referência —
100% na régua do painel), `Base_Pesquisa` (um dos 5 recortes), `Arquivo_Origem`.
Conferido: 0 combinações (cargo, recorte) com valores divergentes — dedup de
5.860 linhas pra 1.210 (242 cargos × 5 recortes) é seguro e é exatamente o que
`upload_faixas_salariais.py` faz antes de gravar no Neon.

**Se a pesquisa de mercado for atualizada no futuro:** reexportar o
consolidado (mesmo processo que gerou o CSV atual, fora deste projeto) e
rodar `python etl/upload_faixas_salariais.py` de novo — truncate + reload.

## Decisão: recorte de pesquisa é filtro, não valor fixo (2026-09-14)

Existem 5 recortes de mercado (GRH ECI Acima de 1000 Colab., GRH ECI Ramo
Econômico, GRH ECI Região Grande SP, Indústria da Construção, Sudeste SP
Grande SP), cada um com seu próprio "salário adequado" por cargo. Perguntado
qual usar como padrão, o usuário respondeu "cada um vai ser um filtro" — não
um recorte fixo. Implementado como `st.selectbox` na barra lateral (não
multiselect — um recorte por vez, porque o "adequado" de cada pessoa muda
conforme o recorte escolhido, misturar não faz sentido).

## Decisão: cruzamento pessoa → mercado por nome do cargo (2026-09-14)

`descricao_cargo` (interno.fato_funcionario_ativo) contra `Cargo_Empresa`
(CSV de mercado) — match exato de string, sem normalização adicional.
Conferido: 214/290 cargos distintos batem (1.302/1.514 = 86% dos colaboradores
ativos). Os ~14% sem match são majoritariamente diretoria/presidência (cargos
de topo não cobertos pela pesquisa) e cargos muito recentes/específicos sem
equivalente. Pessoas sem match ficam de fora do gráfico — contadas à parte
("N sem cargo equivalente") em vez de silenciosamente descartadas.

**Não implementado:** normalização fuzzy de nome de cargo (ex.: variações de
grafia, "Júnior" vs "Jr.") pra aumentar a cobertura. Se a taxa de match virar
um problema, é o próximo passo natural — mas não foi pedido nesta sessão.

## Metodologia do gráfico

Eixo X = salário mensal (R$). Eixo Y = % do salário adequado de mercado,
domínio fixo 60%–140% (`alt.Scale(domain=..., clamp=True)` na camada de
pontos) — especificação exata do usuário. Linhas verdes em 80%/120% (faixa
ideal); linha tracejada cinza em 100% (adequado) — adicionada por clareza
(sem ela, o "adequado" citado no eixo Y não tem uma marca visual própria),
não pedida explicitamente mas direta consequência do que foi pedido.

**Bug corrigido durante a implementação:** a camada de linhas de referência
(rule marks) precisa do MESMO `scale(domain=[60,140])` explícito da camada de
pontos. Sem isso, o Vega-Lite infere o domínio dessa camada a partir só dos
valores [80, 100, 120] com `zero: true` (padrão de escala quantitativa),
estende pra [0, 120], e a escala compartilhada entre as duas camadas vira
[0, 140] em vez do [60, 140] pedido — o eixo aparecia começando em 0.

Pontos fora de 60–140% não são descartados: `clamp: true` gruda eles na borda
do gráfico (não desaparecem), e o texto acima do gráfico deixa claro o
intervalo fixo do eixo.

## Decisão: diretoria/área usam o mesmo mapeamento manual do Headcount (2026-09-15)

`interno.fato_funcionario_ativo` é mirror bruto de `rh.gold.fato_funcionario_ativo`:
`nome_diretoria`/`nome_area` vêm direto do gold, sem a correção manual por
centro de custo que o painel Headcount aplica (`.../Headcount Total/etl/mapping.py`,
`resolve_diretoria_area`) — o gold fica desatualizado depois de reorganizações
(confirmado lendo `extract_databricks_to_neon.py` daquele projeto). Este painel
já tem `centro_de_custo`, `descricao_posicao` e `id_funcionario` na mesma
tabela, então dá pra aplicar a mesma correção sem duplicar pipeline: copiamos
`cc_mapping.json` e `special_mappings.json` do Headcount pra `etl/data/`
(gitignored, mesmo tratamento do CSV de mercado) e a função de resolução pra
`etl/mapping_diretoria.py`. `app.py` substitui `nome_diretoria`/`nome_area`
globalmente com o resultado (filtros, gráfico, Detalhamento, Job Matching).

**Se o Headcount atualizar `cc_mapping.json`/`special_mappings.json`** (novo
CC, reorganização), estes 2 arquivos precisam ser copiados de novo pra cá
manualmente — não há sincronização automática entre os dois projetos.

## Decisão: Mínimo/Máximo Mercado na aba Job Matching = 80%/120% do Adequado (2026-09-15)

A pesquisa de mercado consolidada (`interno.mercado_salarial_muller`) só tem o
valor "adequado" por cargo — sem mínimo/máximo de mercado (os xlsx originais
da pesquisa não hidratam do OneDrive, ver seção abaixo). Perguntado como
preencher as colunas "Mínimo Mercado"/"Máximo Mercado" da aba Job Matching, o
usuário respondeu: "utilize como padrão 80% e 120% do Adequado" — os mesmos
`PISO_IDEAL`/`TETO_IDEAL` já usados na régua de aderência do gráfico de
dispersão. Não precisou mudar o ETL, só o cálculo em `app.py`.

## Bug corrigido: app quebrava no deploy por causa dos JSONs de mapeamento (2026-09-15)

Publicado em github.com/rianlucky/aderencia-salarial e testado no Streamlit
Community Cloud: `FileNotFoundError` na importação de `etl/mapping_diretoria.py`
— `etl/data/cc_mapping.json` não existe no clone (gitignored de propósito,
dado interno de RH), e o módulo lia o arquivo direto no import, sem
try/except, derrubando o app inteiro antes até da tela de login aparecer.

Corrigido com `_load_mapping()`: tenta o arquivo local, senão tenta
`st.secrets["mapping_diretoria"]`, senão cai num dict vazio (log de aviso, o
app continua rodando — todo mundo aparece como "Não informado" pra
Diretoria/Área). Pra ter a correção completa também no deploy, cola o
conteúdo dos 2 JSONs no Secrets do Streamlit Cloud (formato documentado em
`.streamlit/secrets.toml.example` e no README). Mesma lição do que já
aconteceu antes com o CSV de mercado no OneDrive: gitignorar um dado sensível
é a parte fácil — garantir que o código não *precisa* dele pra nem sequer
subir é a parte que faltava.

## Decisão: login unificado em `app_users` (2026-09-15)

Até aqui o login deste painel usava tabela própria (`posicionamento_app_users`),
deliberadamente separada de `app_users` (Headcount) — a razão registrada era
que este painel expõe salário nominal por pessoa, então acesso não devia ser
herdado automaticamente. O usuário pediu explicitamente pra reverter isso:
"unifique tudo em app_users, vou segregar os acessos depois" — mesma senha
em todos os dashboards dele agora, sem controle de acesso por painel até uma
segregação futura (ainda não especificada/implementada). `auth.py` e
`scripts/grant_access.py` apontam pra `app_users` (schema `public`, mesma
tabela do Headcount) desde então.

Conferido antes de trocar: todo mundo que tinha acesso em
`posicionamento_app_users` já tinha conta em `app_users` também (nenhum
e-mail exclusivo) — ninguém perdeu acesso na troca. A tabela antiga
`posicionamento_app_users` não foi apagada (só parou de ser lida) — decisão
de limpá-la ou não fica pro usuário.

## Decisão: painel trabalha só de Executivo pra baixo (2026-09-15)

Diretor, Presidente e Conselheiro (`funcao_cargo` bruto) ficam de fora do
painel inteiro — filtrado logo depois do `load_data()`, antes de qualquer
outro filtro (`NIVEIS_EXCLUIDOS` em `app.py`). Decisão do usuário: "vamos
trabalhar de Executivo para baixo". Esses 3 valores cobrem 20 pessoas no
recorte atual (11 Diretor + 2 Presidente + 7 Conselheiro) — coincide em boa
parte com quem já ficava "sem cargo equivalente" na pesquisa de mercado (ver
seção de cruzamento pessoa→mercado acima), mas agora nem aparecem nos
filtros/tabelas/Job Matching, não só ficam de fora do gráfico.

## Decisão: Mínimo/Máximo de mercado reais, recorte por recorte (2026-09-15)

Descoberta lendo os xlsx atualizados que o usuário colocou em `.Assets/Faixas
Salariais Carreira Muller/Filtros Carreira/` (recortes "GRH ECI - Região
Grande São Paulo" e "Indústria da Construção", ambos retirados em
15/09/2026): o export original da pesquisa TEM mínimo e máximo (bloco "Total
Dinheiro" > Inicial/Final) — só não foram trazidos pro CSV consolidado manual
quando ele foi montado (só guardou o Adequado, decisão registrada mais acima
neste arquivo). `openpyxl` não consegue abrir esses xlsx (`ValueError: Colors
must be aRGB hex values` — cor de fonte inválida no XML gerado pela
ferramenta de origem); `python-calamine` (já instalado, `engine="calamine"`
no `pd.read_excel`) lê sem problema.

Novo script `etl/atualizar_recorte_mercado.py` lê os xlsx originais direto
(não o CSV) e grava `salario_minimo`/`salario_maximo`/`data_retirada` em
`interno.mercado_salarial_muller` (colunas novas, `ALTER TABLE ADD COLUMN IF
NOT EXISTS`) — mas só para os recortes passados em `RECORTES` (delete+insert
por `base_pesquisa`, não truncate da tabela inteira). Os outros 3 recortes
("GRH ECI - Acima de 1000 Colaboradores", "GRH ECI - Ramo Econômico", "Sudeste
SP - Grande São Paulo") continuam só com o Adequado até também serem
atualizados — `app.py` cai no cálculo 80%/120% do Adequado (decisão de
2026-09-15, registrada acima) quando `salario_minimo`/`salario_maximo` vêm
NULL.

`data_retirada` vem da própria planilha (linha 4 traz "NOME DE QUEM RETIROU
DD/MM/AAAA" — quem e quando o relatório foi retirado do Carreira Muller; só a
data é extraída/exibida, o nome não), mostrada na sidebar (abaixo do seletor
de base) e no rodapé da aba Job Matching.

**Atenção:** `etl/upload_faixas_salariais.py` (o script antigo, a partir do
CSV consolidado) faz truncate da tabela inteira e não preenche essas 3
colunas novas — rodá-lo de novo apaga o que `atualizar_recorte_mercado.py` já
tinha gravado pros recortes atualizados (ver aviso no próprio arquivo).

## Ambiente de teste (Windows, OneDrive)

Descoberta desta sessão: arquivos "somente na nuvem" do OneDrive (atributo
`RECALL_ON_DATA_ACCESS`) podem falhar ao hidratar mesmo com `dangerouslyDisableSandbox`
e mesmo depois do usuário abrir o arquivo manualmente — não é um problema de
sandbox da ferramenta, é o próprio OneDrive/Windows. Quando isso acontece de
novo, verificar se existe um export/CSV alternativo já pronto (como aconteceu
aqui) antes de insistir em ler o xlsx original.
