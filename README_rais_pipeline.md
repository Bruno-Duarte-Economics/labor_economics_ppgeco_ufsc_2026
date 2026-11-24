# Pipeline RAIS: estoque e saldo de emprego por município

Última atualização: 22/11/2026

## 1. Objetivo

Extrair da RAIS (microdados de vínculos) o **estoque de emprego em 31/12** por município do **PR, SC e RS**, de **1985 a 2025**, no total e por atividade econômica, e calcular o **saldo** (variação do estoque entre anos consecutivos).

A atividade é classificada em **subsetor IBGE para a série inteira** (25 categorias). Nenhuma classificação cobre todo o período, então o subsetor é nativo em parte dos anos e derivado da CNAE nos demais (seção 6).

Uso previsto: alimentar o controle sintético em nível de município (Ensaio 1 da dissertação). O papel exato da RAIS no desenho (preditores, desfecho alternativo ao PIBpc, ou ambos) ainda está em definição.

## 2. Estrutura da pasta

```
05. Python/
├── .venv/                      ambiente virtual
├── requirements.txt            lista de pacotes
├── rais_pipeline.py            script (linha de comando)
├── README_rais_pipeline.md     este arquivo
└── data/
    ├── raw/<ano>/              arquivos .7z baixados do FTP
    └── processed/              parquets e tabelas de correspondência
```

Os caminhos do script são relativos à pasta de onde ele é executado, que deve ser `05. Python`.

## 3. Ambiente

Pacotes: `pandas`, `numpy`, `pyarrow`, `py7zr`, `pysyncon`, `matplotlib` (arquivo `requirements.txt`).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Se o `python` apontar para o Python da Microsoft Store (caminho com `WindowsApps`) em vez do `.venv`, usar o caminho completo: `.\.venv\Scripts\python.exe`.

O botão de executar do VS Code roda o script sem argumentos e gera o erro `the following arguments are required: cmd`. O script precisa de um comando, digitado no terminal.

## 4. Comandos

| Comando | O que faz | Deixa no disco |
|---|---|---|
| `download` | Baixa os `.7z` do FTP do PDET/MTE | `data/raw/<ano>/` |
| `inspect` | Mostra a primeira linha, o separador e as colunas de um arquivo | nada (só imprime) |
| `extract` | Filtra e conta vínculos por município, subsetor e CNAE (em **classe**, 5 dígitos) | `data/processed/rais_mun_<ano>.parquet` |
| `coverage` | Mostra, por ano, a % de vínculos com cada classificação de atividade | nada (só imprime) |
| `crosswalk` | Constrói a correspondência CNAE → subsetor e mostra sua qualidade e a origem do subsetor por ano | CSVs em `data/processed/` |
| `transicoes` | Compara os subsetores nos anos em que a origem da classificação muda (1994, 2006 e 2015) | nada (só imprime) |
| `build` | Junta os anos e calcula estoque e saldo | `data/processed/estoque_saldo_<nivel>.parquet` |
| `painel` | Exporta os dois painéis finais, cada um em um único arquivo (com subsetor e total por município) | `data/processed/painel_rais_mun_subsetor.*` e `painel_rais_mun_total.*` (parquet e CSV) |

### Ordem de execução

```powershell
# 1. Conferir os arquivos disponíveis (não baixa nada)
python rais_pipeline.py download --years 1985-2017 --match PR,SC,RS --list
python rais_pipeline.py download --years 2018-2025 --match SUL --list

# 2. Baixar (se a conexão cair, repetir o mesmo comando)
python rais_pipeline.py download --years 1985-2017 --match PR,SC,RS
python rais_pipeline.py download --years 2018-2025 --match SUL

# 3. Conferir o layout de um arquivo
python rais_pipeline.py inspect --file "data\raw\2023\RAIS_VINC_PUB_SUL.7z"

# 4. Extrair. De 1994 em diante é necessário o esquema atual (CNAE em classe).
#    1985-1993 só tem subsetor: os parquets já gerados continuam válidos.
python rais_pipeline.py extract --years 1994-2025

# 5. Diagnósticos
python rais_pipeline.py coverage
python rais_pipeline.py crosswalk
python rais_pipeline.py transicoes

# 6. Painéis
python rais_pipeline.py build --nivel total
python rais_pipeline.py build --nivel subsetor

# 7. Painéis finais (os dois, de uma vez)
python rais_pipeline.py painel

# Ou cada um com sua janela de anos (ex.: total desde 1985 e subsetor desde 1995)
python rais_pipeline.py painel --nivel total
python rais_pipeline.py painel --nivel subsetor --ano-inicial 1995
```

Níveis do `build`: `total` (padrão), `subsetor` (harmonizado), `cnae95` e `cnae20` (divisão, só nos anos em que existem).

Observações:

- O `download` mostra o progresso a cada ~100 MB. Se for interrompido, repetir o mesmo comando retoma de onde parou.
- O `extract` imprime uma linha a cada 1 milhão de linhas lidas. Arquivos regionais grandes levam vários minutos, e a extração de 1994 a 2025 é demorada; pode ser feita em blocos (por exemplo, `--years 1994-2005`, depois `2006-2017` e `2018-2025`).
- `extract --skip-existing` pula anos cujo parquet já existe. Usar apenas se o ano foi extraído com **todos** os arquivos e no esquema atual.
- O `build` imprime, ao final, o número de municípios distintos e, nos níveis por atividade, a lista de categorias.
- Se o `crosswalk`, o `transicoes` ou o `build --nivel subsetor` encontrarem parquets no esquema antigo (CNAE só em divisão) a partir de 1994, o erro indica quais anos refazer.

## 5. Lógica

Os microdados são grandes (vários GB por ano). O trabalho é dividido em etapas, e cada uma grava o resultado em disco para a seguinte:

1. **Download**: arquivos compactados do FTP.
2. **Extração**: cada arquivo é descompactado em pasta temporária e lido em pedaços de 1 milhão de linhas (*chunks*), apenas com as colunas necessárias. Em cada pedaço, mantêm-se só os vínculos ativos em 31/12 de municípios do PR, SC e RS, e os vínculos são contados por município, subsetor, CNAE 95 (classe) e CNAE 2.0 (classe). O resultado agregado, muito menor que o original, é gravado em um parquet por ano.
3. **Harmonização**: a partir dos parquets, o subsetor IBGE é completado nos anos em que não existe, por correspondência com a CNAE (seção 6).
4. **Diagnóstico e painel**: trabalham apenas sobre os parquets já agregados, por isso são rápidos e não voltam aos arquivos brutos.

**Parquet** é um formato colunar binário: gera arquivos menores que o CSV, lê rápido e preserva os tipos (códigos continuam texto, com zeros à esquerda). Leitura: `pd.read_parquet("caminho.parquet")`.

## 6. Decisões metodológicas e motivos

### Medidas

- **Estoque em 31/12 (`Vínculo Ativo 31/12 == 1`)**: a RAIS é um registro anual, e o estoque de 31/12 é a medida padrão de emprego formal.
- **Saldo = variação do estoque entre 31/12 de *t−1* e 31/12 de *t***: não equivale ao saldo de admissões menos desligamentos do CAGED. Na escrita, convém chamá-lo de variação do estoque.
- **Saldo vazio quando o ano anterior não existe na série**: evita que uma diferença cubra mais de um ano. O primeiro ano de cada série também fica sem saldo.
- **Nível `total`**: soma todas as atividades e independe de classificação, por isso cobre os 41 anos.

### Harmonização em subsetor IBGE

Nenhuma classificação cobre a série inteira (seção 7). A escolha foi usar o subsetor IBGE em todos os anos:

- **Nativo** em 1985–1993 e de 2015 em diante.
- **Passo A, 2006–2014**: o subsetor é derivado da **CNAE 2.0 (classe)**, por uma correspondência aprendida nos anos em que subsetor e CNAE 2.0 coexistem nativamente (2015 em diante).
- **Passo B, 1994–2005**: o subsetor é derivado da **CNAE 95 (classe)**, por uma correspondência aprendida em todos os anos que já têm subsetor (nativo ou derivado no passo A) junto com CNAE 95.
- **Passos C e D (reserva)**: classes CNAE 95 sem correspondência (por exemplo, classes que não aparecem nos anos em que o subsetor é conhecido) usam a correspondência pelo **grupo** (3 dígitos) e, depois, pela **divisão** (2 dígitos), mas só quando o grupo ou a divisão cai em um único subsetor em pelo menos 90% dos vínculos (`MIN_PUREZA` no início do script). A origem de cada linha fica registrada (`nativo`, `cnae20`, `cnae95`, `cnae95_grupo`, `cnae95_div`).
- **Correspondência modal**: cada classe CNAE recebe o subsetor com mais vínculos. A **pureza** mede a parcela dos vínculos da classe que cai no subsetor escolhido (100% = sem ambiguidade). O comando `crosswalk` mostra a pureza ponderada.
- **Por que classe e não divisão**: uma divisão CNAE pode se repartir entre mais de um subsetor, e a classe resolve a maior parte dessa ambiguidade. Por isso o `extract` guarda a CNAE em classe (5 dígitos).
- **Categoria `00`**: vínculos sem subsetor identificável (sem classificação, ou com classe CNAE sem correspondência) ficam em `00` no painel por subsetor, para que a soma dos subsetores feche com o total.
- **Pontos de transição (1994, 2006 e 2015)**: a origem do subsetor muda nesses anos, e o saldo nesses pontos pode refletir reclassificação, e não variação de emprego. O painel por subsetor traz a coluna `quebra_classificacao` (verdadeira nesses anos) para permitir excluí-los ou tratá-los. A avaliação feita com o `transicoes` está na seção 7.
- **Correspondências gravadas** em `data/processed/crosswalk_cnae20_subsetor.csv` e `crosswalk_cnae95_subsetor.csv`, junto com `diagnostico_origem_subsetor.csv` (origem do subsetor por ano), para consulta e para o apêndice metodológico.

### Painéis finais (`painel`)

Duas versões, cada uma em um único arquivo (parquet e CSV):

**1. Com subsetor** (`painel_rais_mun_subsetor`), com o subsetor IBGE harmonizado na série inteira:

| Coluna | Conteúdo |
|---|---|
| `ano` | ano da RAIS |
| `uf` | sigla do estado (PR, SC ou RS), obtida dos dois primeiros dígitos do código do município |
| `mun` | código do município, 6 dígitos (texto) |
| `subsetor` | subsetor IBGE harmonizado (`01` a `25`, além de `00`, `98` e `99`) |
| `estoque` | vínculos ativos em 31/12 no subsetor |

**2. Total por município** (`painel_rais_mun_total`): soma de todos os vínculos formais ativos em 31/12, por município e ano. Colunas `ano`, `uf`, `mun` e `estoque`. Não depende de classificação de atividade e inclui os vínculos sem atividade identificada, por isso cobre os 41 anos e é a versão mais robusta.

Observações:

- **A soma dos subsetores fecha com o total**, ano a ano (o comando confere quando gera os dois), porque os vínculos sem subsetor ficam na categoria `00`.
- **Painéis balanceados**: toda combinação município (× subsetor) × ano aparece, com estoque 0 quando não há vínculos. Municípios criados no período aparecem com zeros antes da criação, e esses zeros são artificiais.
- **Janela de anos**: `--ano-inicial` corta o painel. Sem `--nivel`, vale para os dois; com `--nivel`, o outro arquivo não é alterado. Cada execução sobrescreve o arquivo do seu nível, e o nome não registra a janela, então convém anotá-la.
- **Sem saldo e sem marca de quebra**: os painéis têm só as colunas acima. O saldo e a coluna `quebra_classificacao` (1994, 2006 e 2015) ficam em `estoque_saldo_subsetor.parquet` e `estoque_saldo_total.parquet`, gerados pelo `build`.
- **CSV**: separador `;` e UTF-8 com BOM. O Excel remove os zeros à esquerda de `mun` e `subsetor` ao abrir o arquivo; em Stata, R e Python, ler essas colunas como texto.

### Leitura e filtros

- **Filtro por prefixo do código do município** (PR = 41, SC = 42, RS = 43): o código da RAIS tem 6 dígitos, sem o dígito verificador do IBGE. Vale tanto para arquivos por UF quanto para os regionais (`SUL`). Se o código vier com 7 dígitos (layout novo), o último é descartado.
- **Coluna de município = `Município`**: é a única disponível em 1985. A partir de 2006 existe também `Mun Trab`, não utilizada.
- **Todas as colunas lidas como texto (`dtype=str`)**: preserva zeros à esquerda em códigos.
- **Limpeza de códigos de atividade**: os arquivos trazem `{ñ class}`, valores negativos e `00000` quando a classificação não se aplica. Esses valores viram vazio.
- **Separador detectado pela primeira linha**: o layout de 2023 em diante não segue o `;` dos anteriores.

### Download

- **Arquivo `.part`, com retomada**: o arquivo só é renomeado ao final, então um download interrompido não é confundido com um completo. Se a conexão cair, o script reconecta e retoma do ponto em que parou (até 5 tentativas), e confere o tamanho final com o informado pelo servidor. Cada arquivo usa uma conexão própria, porque uma conexão parada durante um download longo é derrubada pelo servidor.
- **Listagem do FTP em `latin-1`**: há nomes de arquivo fora do UTF-8 (erro `UnicodeDecodeError` em 2024).

## 7. O que se sabe sobre os dados

### Organização do FTP (`ftp://ftp.mtps.gov.br/pdet/microdados/RAIS/<ano>/`)

- **1985 a 2017**: um arquivo por UF (`PR2015.7z`, `SC2015.7z`, `RS2015.7z`). Em anos antigos há também `IGNORADO*`/`IGNORANDOS*` (vínculos sem UF identificada), não utilizados.
- **2018 a 2025**: arquivos regionais (`RAIS_VINC_PUB_SUL.7z`, que reúne PR, SC e RS). Os arquivos `NI` e de outras regiões não são utilizados.
- Arquivos de estabelecimentos (`ESTB*`, `Estb2006.zip`) são ignorados.
- Os dicionários de layout ficam na página de Microdados RAIS e CAGED do PDET (gov.br/trabalho-e-emprego).

### Disponibilidade das classificações (`coverage`, série de 1985 a 2025)

Percentual dos vínculos ativos com a classificação preenchida:

| Período | Subsetor IBGE | CNAE 95 | CNAE 2.0 |
|---|---|---|---|
| 1985–1993 | 99,6% em 1985, caindo até 84,1% em 1993 | não existe | não existe |
| 1994–2005 | não existe | 96,0% em 1994, 99,4% em 1995, ~100% a partir de 1998 | não existe |
| 2006–2014 | não existe | 100% | 100% |
| 2015–2025 | 100% | 100% | 100% |

Estoque de vínculos ativos em 31/12 (PR + SC + RS), em milhões: 3,45 (1985), 4,14 (1994), 5,83 (2005), 8,55 (2014), 8,09 (2016), 8,23 (2018), 8,27 (2020), 9,27 (2022), 9,58 (2023), 9,87 (2024), 10,16 (2025).

Leituras:

- Entre 1985 e 1993 só existe subsetor, e a parcela sem subsetor cresce ao longo desses anos (de 0,4% para 15,9%).
- Não há descontinuidade visível entre os arquivos por UF (até 2017) e os regionais (a partir de 2018): 8,14 milhões em 2017 e 8,23 milhões em 2018.
- A queda de 2014 para 2016 é compatível com a recessão do período. O crescimento de 2023 a 2025 (cerca de 3% ao ano) é compatível com os anos anteriores, o que não indica ano parcial em 2025; ainda não foi comparado com totais oficiais.
- Os anos 1985, 2006 e 2017, testados no início só com SC, foram refeitos com PR, SC e RS.

### Correspondência CNAE → subsetor (primeira execução do `crosswalk`)

- **CNAE 2.0 → subsetor**: 669 classes, pureza ponderada de 99,7%.
- **CNAE 95 → subsetor**: 562 classes, pureza ponderada de 99,8%.
- A pureza é medida na amostra em que a correspondência é aprendida (anos com subsetor conhecido). Ela mostra que cada classe cai quase sempre em um único subsetor, mas não mede a exatidão da retroprojeção para 1994–2014.

Origem do subsetor por ano nessa execução (antes dos passos de reserva C e D):

| Período | Origem | % do estoque sem subsetor |
|---|---|---|
| 1985–1993 | nativo | 0,4% a 15,9% |
| 1994–2001 | CNAE 95 (90,4% a 92,5% do estoque) | 7,5% a 9,6% |
| 2002–2005 | CNAE 95 (98,2% a 99,1%) | 0,9% a 1,8% |
| 2006–2014 | CNAE 2.0 | 0% |
| 2015–2025 | nativo | 0% |

Classes CNAE 95 sem correspondência nessa execução (maiores, em vínculos acumulados): `01503` (571.723), `80306` (400.468), `40100` (210.954), `55115` (182.034), `80217` (163.574), `75140` (128.616), `80128` (124.931), `74152` (109.320), `80225` (95.692). Além disso, 2.056.163 vínculos não têm nenhum código de atividade (compatível com a parcela sem subsetor de 1985–1993 e com os poucos casos sem CNAE em 1994–1997). Hipótese: são classes que existem na CNAE 95 dos anos 1990 mas não aparecem nos anos em que o subsetor é conhecido, o que explica o patamar de ~7,7% em 1998–2001 e a queda em 2002. Os passos de reserva C e D foram criados para tratar esses casos e precisam ser avaliados em nova execução do `crosswalk`.

### Segunda execução do `crosswalk` (com os passos de reserva C e D)

- Correspondência por **grupo** (3 dígitos) da CNAE 95: 221 chaves, pureza ponderada de 99,0%, 214 aceitas (pureza ≥ 90%).
- Correspondência por **divisão** (2 dígitos): 60 chaves, pureza ponderada de 96,6%, 49 aceitas.
- A parcela sem subsetor em 1994–2001 caiu de 7,5%–9,6% para 4,0% em 1994, 0,6% em 1995 e valores próximos de zero a partir de 1996. Em 1995–2001, cerca de 6,3% do estoque usa a correspondência por grupo e 1,2%–1,5% a por divisão; em 2002, 0,7% e 1,2%; em 2003–2005, cerca de 0,5% cada.
- Restam sem subsetor: os vínculos sem qualquer código de atividade (2.056.163 no total, com anos de 1985 a 2008, concentrados em 1985–1993 e em 1994) e 9 vínculos de 2006–2007 (CNAE 95 `13234` com CNAE 2.0 `07235`).

### Painel por subsetor (`build --nivel subsetor`)

- 1.371.860 linhas = 41 anos × 33.460 combinações, correspondendo a **1.195 códigos de município** e **28 categorias**: `00`, `01` a `25`, `98` e `99`.
- Os 1.195 códigos são 4 a mais que os 1.191 municípios atuais do PR, SC e RS.
- As categorias `98` e `99` aparecem no painel e têm estoque zero nos três anos de transição examinados (1993/94, 2005/06 e 2014/15).

### Transições da classificação (`transicoes`)

- **2014 → 2015 (CNAE 2.0 derivada → nativo)**: transição limpa. As participações dos subsetores mudam no máximo 0,4 ponto percentual, e as variações acompanham o ciclo (por exemplo, queda no subsetor `15` em 2015 e 2016).
- **2005 → 2006 (CNAE 95 → CNAE 2.0)**: quase toda limpa (participações dentro de ±0,4 pp), com exceção do subsetor `23`, que sobe 72,7% em 2006 (de 3,1% para 5,0% do estoque, +1,9 pp) e cai 33,8% em 2007. O subsetor `24` perde 1,4 pp em 2006. O movimento oposto sugere vínculos migrando entre esses dois subsetores na codificação de 2006. Ao que tudo indica, `23` é Ensino e `24` é Administração Pública direta e autárquica, mas isso deve ser conferido no dicionário de layout. A causa não foi investigada em nível de classe CNAE 2.0.
- **1993 → 1994 (nativo → CNAE 95 derivada)**: há quebra clara. Vários subsetores variam de 20% a 80% em 1994 (por exemplo, `24`: +77,0%, `22`: +53,0%, `20`: +46,9%, `25`: +66,7%, `23`: +183,9%) e outros caem (`19`: −30,5%, `21`: −28,9%), enquanto o estoque total cresce 3,5%. A parcela `00` cai de 15,9% para 4,0%. O subsetor `24` já havia caído 34% em 1993, o que é compatível com a concentração de vínculos sem classificação nele em 1993. Os subsetores 1985–1993 (definição nativa) e de 1994 em diante (derivados da CNAE) não são comparáveis em nível.
- Consequência: para análises por subsetor, tratar 1993/1994 como quebra de série. A série total não é afetada.

### Layout de 2023 em diante (conferido com `inspect`)

- Separador `,`, com os nomes das colunas entre aspas e no formato `Nome - Código` (por exemplo `Município - Código`, `Ind Vínculo Ativo 31/12 - Código`, `IBGE Subsetor - Código`, `CNAE 95 Classe - Código`, `CNAE 2.0 Classe - Código`); 62 colunas.
- O script detecta o separador pela primeira linha e aceita esses nomes. A extração de 2023, 2024 e 2025 funcionou, com as três classificações 100% preenchidas.

## 8. Problemas encontrados e soluções

| Problema | Causa | Solução |
|---|---|---|
| `the following arguments are required: cmd` | Script executado sem o comando | Rodar pelo terminal com o comando (`download`, `extract`, ...) |
| `No module named 'pandas'` | Pacotes instalados fora do `.venv` / Python da Store | Usar `.\.venv\Scripts\python.exe` e reinstalar pelo `requirements.txt` |
| `UnicodeDecodeError` na listagem de 2024 | Nome de arquivo fora do UTF-8 no servidor | `ftp.encoding = "latin-1"` |
| Download interrompido tratado como completo | Arquivo parcial já existia | Download via `.part` e renomeação ao final |
| Download parou em 2021 (`.part` de ~551 MB) | Conexão FTP interrompida durante um arquivo grande | Retomada automática com novas tentativas |
| `TimeoutError` no fim de alguns downloads (2022, 2025) | Servidor demora a encerrar a transferência | Retomada automática; os arquivos foram concluídos |
| `extract` terminou em 2020 sem erro | Não havia arquivo completo de 2021 em diante (`.part` é ignorado) | Concluir o download e extrair os anos seguintes |
| `KeyError` na coluna `mun` ao extrair 2023 | Layout novo: separador `,` e nomes no formato `Nome - Código` | Detecção do separador e novos nomes aceitos |
| 7,5% a 9,6% do estoque de 1994–2001 sem subsetor | Classes CNAE 95 sem correspondência no período em que o subsetor é conhecido | Correspondência de reserva por grupo e divisão: parcela sem subsetor cai para ~0% a partir de 1996 |
| Categorias estranhas nas colunas de atividade | Valores `{ñ class}`, `-1`, `00000` | Função de limpeza de códigos |
| Parquets de 1994 a 2022 sem CNAE em classe | Esquema antigo guardava só a divisão | Refazer `extract --years 1994-2025` |

## 9. Pendências e pontos de atenção

1. **1.195 códigos de município** (4 além dos 1.191 atuais): identificar quais são (possíveis códigos genéricos, antigos ou inválidos) e decidir se são mantidos.
2. **Categorias `98` e `99`**: conferir no dicionário de layout o que significam, em quais anos têm vínculos e se devem ser agrupadas com `00` (não classificado).
3. **Subsetores `23` e `24` em 2006**: investigar, em nível de classe CNAE 2.0, a movimentação entre os dois (+72,7% e −33,8% do subsetor `23` em 2006 e 2007).
4. **Quebra de 1993/1994**: decidir como tratar a série por subsetor (por exemplo, iniciar o período em 1994, ou usar categorias mais agregadas), conforme os anos de tratamento a analisar. A série total independe disso.
5. Validar os totais de vínculos contra números oficiais publicados por UF (inclusive 2025).
6. **Municípios criados no período**: aparecem com estoque 0 antes da criação, gerando saltos artificiais. Tratar no donor pool (áreas mínimas comparáveis ou exclusão).
7. **Quebra recente**: a captação via eSocial pode alterar a cobertura nos anos finais; checar as séries antes de usar o pré-tratamento.
8. **Valores nominais**: o script atual conta vínculos; se remuneração for incluída depois, será necessário deflacionar (IPCA).
9. Definir o papel da RAIS no controle sintético (preditores, desfecho alternativo ou ambos) e o recorte do donor pool.
