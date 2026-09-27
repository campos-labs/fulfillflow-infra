# FulfillFlow Infra — Estado de entrega e evolução

## 1. Estado atual

**Observabilidade: correlação consolidada**, na branch `feature/v1.2-observability`,
a partir de `v1.1.0-rc.1` (`92089b8`). Descoberta offline e dois casos diagnósticos
integrados estão concluídos: fluxo saudável e trabalho publicado aguardando consumo.
O [índice técnico e registros publicados](docs/evidence/observability/README.md)
permitem conferir cobertura e limites sem depender dos artefatos locais selecionados.
Nó parado; sem OpenTelemetry instalado, nova carga agendada, merge ou release v1.2.
A próxima fatia está delimitada abaixo; as avaliações históricas não são reabertas.

**Comparação de capacidade fixa e adaptativa concluída e consolidada na
v1.1.0-rc.1.** O fechamento integra `feature/v1.1-autoscaling-kind` à `main`.
A [página da pré-release](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1)
identifica tag, commit e anexos; as referências medidas permanecem no relatório.

As nove tentativas foram preservadas, incluindo a primeira adaptativa da sessão
interrompida. A continuação terminou com zero posições pendentes. Essas campanhas
permanecem encerradas; novos ensaios pertencem à exploração delimitada da seção 4. Resultados, método, sensibilidade e limites
estão no [relatório de capacidade](docs/SCALING_EVALUATION.md); os três ZIPs em
`docs/evidence/scaling/archives` eliminam a dependência de pastas locais para sua
leitura. A imagem, o código da aplicação e o instrumento medido permanecem congelados.

## 2. Entregas e responsabilidades

| Referência | Entrega e situação |
| --- | --- |
| [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0) | Recuperação operacional em Kind; [relatório e evidências](docs/OPERATIONAL_EVALUATION.md) preservados |
| [v1.1.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1) | Pré-release de capacidade fixa/adaptativa, scripts versionados, comparação concluída, gráficos e três pacotes |
| Aplicação consumida | FulfillFlow v1.3.0-rc.1, SHA `9e3a135a00db218643633c7165d3106f0c8285e1`; nenhuma alteração neste fechamento |
| Azure | Terraform e exemplos AKS/ACR são referências ainda não implantadas; não condicionam o aceite local |

README apresenta a entrega e orienta a navegação. DESIGN define contratos e
arquitetura. O guia `k8s/README.md` reúne pré-requisitos e comandos. Os relatórios
registram métodos executados, resultados e respectivas evidências. Este documento
acompanha estado de entrega e decisões futuras, sem duplicar as tabelas analíticas.

## 3. Fechamento e verificação

O [relatório](docs/SCALING_EVALUATION.md) preserva as nove tentativas, a interrupção
do bloco 1 e a análise dos blocos contínuos. Os
[três pacotes e checksums](docs/evidence/scaling/archives) e o
[manifesto](docs/evidence/scaling/manifest.json) permitem reprodução offline;
a qualificação tem seleção identificada de metadados. Scripts permanecem em
`scripts/`, sem depender de launchers `.local.ps1`.

O fechamento inclui revisão visual, inspeção do conteúdo publicável, testes e
checagem de integridade das evidências. A CI Linux/Windows verifica código,
documentos, reprodução offline, schemas e planos Terraform simulados; não executa
a comparação no Kind. Os resultados de CI ficam vinculados ao commit no GitHub.

A [nota da versão](docs/releases/v1.1.0-rc.1.md) resume entrega e limites.
A tag identifica a consolidação; `6932632` identifica o instrumento medido e
`5ca5878`, o coordenador da continuação. Os anexos da release são cópias exatas
dos ZIPs versionados, sem recompactação. Não mover tags nem substituir pacotes
publicados: uma correção posterior deve ter identidade própria.

<a id="3-extensões-possíveis"></a>

## 4. Exploração de observabilidade

### Resultado consolidado

**Questão técnica:** o que podemos localizar entre aceite, resultado por etapa e
confirmação do observador usando sinais existentes? Os dois casos ligaram nove
registros de cada evento às consultas públicas dos três serviços. A contribuição
nova é a reconstrução do caminho e dos limites da observação; conclusão sem reenvio
já estava demonstrada na avaliação de recuperação. Não são nove repetições por caso.

A [matriz de cobertura, método e índice das evidências](docs/evidence/observability/README.md)
concentra a análise. O plano registra somente estado e próximas decisões. A falha
anterior ao envio e a sucessora concluída permanecem separadas. O
[diário anterior à consolidação](https://github.com/campos-labs/fulfillflow-infra/blob/fcff02e0938675af0be51950ba444cca4b0da9a5/RELEASE_PLAN.md#4-exploração-de-observabilidade)
preserva protocolos prospectivos, correções e limites de cada janela.

**Decisão:** encerrar os cenários saudável e de pendência; sem repetição manual ou
carga adicional para confirmá-los. A coleta atual não mede overhead causal ou
tracing distribuído, nem resolve os 503 históricos. Scripts permanecem versionados;
claims e diretórios existentes não devem ser apagados para forçar novo ensaio.

### Próxima fatia: uma chamada HTTP interna

**Pergunta:** qual trecho de uma chamada conseguimos localizar que antes aparecia
somente como duração total ou `SERVICE_UNAVAILABLE`? Primeiro, um GET saudável
através de observador → Core → Tracking. A verificação funcional e os IDs públicos
continuam independentes dos traces. Não envolver webhook, workers, carga de escala,
transações SQL instrumentadas ou falha controlada no primeiro passo.

O código congelado oferece um ponto concreto: [ServiceClient](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/http/internal.py)
repassa request ID e contexto HTTP, mas não cria spans; traduz erros HTTP/timeout
em indisponibilidade, e a leitura também pode traduzir resposta inválida. A
[camada Core → Tracking](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/core/tracking_client.py)
fornece a fronteira. Um span de transporte sozinho pode mostrar HTTP 200 mesmo
quando a validação posterior da resposta falha; registrar essas categorias
separadamente, sem expor resposta ou exceção bruta.

| Parte | Informação pretendida | Limite/aceite |
| --- | --- | --- |
| Observador | Agendamento, início/fim HTTP e contexto enviado | Relógio monotônico próprio, sem atribuir toda espera ao servidor |
| Core servidor e cliente interno | Rota, destino lógico, duração do hop, status/categoria permitida | Ligar contexto e request ID; separar transporte, resposta remota e validação |
| Tracking servidor | Entrada/saída da mesma chamada | Ausência de span não prova ausência de execução; conferir captura/exportação |
| Estado público | GET e conteúdo esperado | Telemetria não substitui resultado funcional |

A documentação de [HTTPX](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/httpx/httpx.html)
e [FastAPI](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)
oferece pontos de instrumentação e hooks. É uma proposta, não compatibilidade testada:
a implementação deve fixar versões/lock, definir atributos permitidos e testar
remoção de query strings, headers secretos, corpos e mensagens de exceção antes
de exportar. Não copiar todos os atributos padrão indiscriminadamente.

**Preparação mínima:** definir uma referência instrumentada própria da aplicação
v1.3, com checkout isolado do trabalho em paralelo, feature flag desabilitada por
padrão e imagem identificada. Não sobrepor tags/imagens históricas ou injetar patches
ocultos pela infraestrutura. Começar com SDK/instrumentação HTTP necessária e um
único destino local; não instalar Operator, Prometheus, Grafana ou Azure Monitor
como pré-requisito. A identidade e o orçamento dessa nova execução devem estar
registrados antes do início; esta consolidação não instala nem executa o runtime novo.

**Aceite da fatia:** identificar a mesma chamada nas fronteiras instrumentadas,
confrontar resposta pública, relatar marcos ausentes e saúde da exportação. Medir
volume e recursos disponíveis sem alegar overhead causal. Se um trace apenas
reempacotar a informação existente, manter como complemento; se localizar uma
fronteira antes invisível, decidir uma perturbação única com resultado esperado.
Não depender de reproduzir o 503 histórico para justificar continuidade.

Em futura investigação temporal, observar estado de negócio e rollout **em paralelo**,
com diários separados, para não adiar uma consulta deliberadamente até a prontidão.
Não modificar retroativamente os casos atuais: a espera sequencial está documentada.

### Guardas para qualquer nova execução

Avisar a janela crítica e conferir tomada, containers e margem: 5 GiB de entrada,
2 GiB durante execução. Não reiniciar Docker/WSL, apagar volumes ou reduzir guardas.
Fixar previamente destino, número de chamadas e teto de tempo; não repetir até passar.
Preparação, testes offline e ajustes rotineiros seguem dentro do escopo; parar diante
de alteração de contrato, risco do ambiente, custo externo ou mudança relevante do
desenho. Manual ou execução direta têm o mesmo valor se o protocolo for equivalente.
Não há nova carga autorizada pelos registros de campanhas já encerradas.

<a id="4-continuidade-condicionada"></a>

### Continuidade após a exploração

Prometheus e verificações de segurança permanecem possibilidades por lacuna
concreta, sem integrar automaticamente este incremento. Se o ganho diagnóstico
for pequeno, registrar complemento breve e voltar à avaliação de viabilidade AKS;
isso não autoriza provisionamento ou migração automática.

**AKS:** extensão opcional de portabilidade e funcionamento selecionado, com prints
e evidências do ambiente efetivamente usado. ACR depende da implantação escolhida.
Os resultados quantitativos do Kind não se tornam resultados de nuvem. Uma
comparação correspondente no AKS exigiria protocolo e repetições próprios;
instrumentação e ambiente não devem mudar juntos numa comparação que pretenda
atribuir efeito somente à instrumentação.

As consultas anteriores não estabeleceram uma configuração Azure provisionável.
Antes de qualquer apply, revisar assinatura, região, quotas, restrições de SKU,
capacidade, acesso, orçamento, encerramento e custos residuais conforme o
[guia Terraform](infra/README.md). Quota positiva não garante alocação. Não iniciar
nuvem, alterar limites de carga ou refatorar a aplicação a partir desta consolidação.

## 5. Preservação e histórico

Os relatórios substituem o diário preparatório na leitura principal. O
[histórico completo até o encerramento](https://github.com/campos-labs/fulfillflow-infra/blob/58f4483e0fdb2e5273b9b533d9173de494818a3c/RELEASE_PLAN.md)
continua acessível por commit imutável; as pastas originais permanecem intactas.
Identificadores como `a2-*`, `b1-p1-*` e nomes históricos de scripts são mantidos
somente para rastrear protocolos e arquivos. Não representam novos incrementos pendentes.

As três pastas de tentativas em cada ZIP são completas. Configurações privadas,
credenciais, dumps e kubeconfigs continuam fora do Git. Os pacotes permitem
conferir dados e gráficos sem o notebook original; não incluem imagem Docker nem
garantem recriação idêntica de hardware/runtime ou restauração de backup independente.
Novas medições exigem ambiente e protocolo identificados, diretórios novos e
encerramento limitado, preservando resultados desfavoráveis e falhas de execução.

Versões seguem a convenção: correções compatíveis incrementam PATCH, capacidades
compatíveis MINOR e mudanças incompatíveis MAJOR; candidatas usam `-rc.N`.
Não reservar automaticamente uma versão para cada ferramenta ou ambiente.
