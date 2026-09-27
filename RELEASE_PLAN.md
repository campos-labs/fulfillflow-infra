# FulfillFlow Infra — Estado de entrega e evolução

## 1. Estado atual

**Incremento ativo: descoberta de observabilidade**, na branch
`feature/v1.2-observability`, a partir de `v1.1.0-rc.1` (`92089b8`). Contratos em
[DESIGN §8.8](DESIGN.md#88-exploração-de-observabilidade). A exploração não reabre
as campanhas concluídas nem promete uma nova campanha ou release. A correlação
offline foi implementada; a prova integrada está preparada para execução manual
com o notebook reservado e nova conferência de margem.


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

**Questão técnica:** quais partes do intervalo entre aceite, conclusão por etapa
e confirmação pelo observador conseguimos localizar com os sinais disponíveis,
e qual informação adicional justificaria instrumentação?

### Um incremento, com progressão limitada

1. **Mapa de cobertura sem carga.** Ler a referência congelada e os pacotes
   publicados. Relacionar marcos, IDs, relógios, fontes e lacunas, incluindo o
   observador. Usar uma seleção declarada para ilustrar correlação, sem recalcular
   comparações ou escolher exemplos como estimativa representativa. Registrar
   quando uma etapa é apenas inferida ou não observável.
2. **Prova mínima, se houver lacuna verificável.** Preparar o menor mecanismo que
   responda a essa lacuna, com versões fixadas e testes offline primeiro. Preferir
   OpenTelemetry quando houver necessidade de tracing; não instalar Operator,
   Prometheus, Grafana ou serviço gerenciado por padrão. Se apenas a correlação
   dos logs já responder à questão, consolidar esse resultado sem adicionar stack.
3. **Verificação local delimitada e decisão.** Quando a referência/runtime e a
   coleta estiverem identificados, executar até três ensaios funcionais distintos,
   com até três eventos novos por ensaio, sem carga de capacidade nem falha real
   de aplicação injetada. Verificar identidade, conclusão e cobertura da observação.
   Falhas sintéticas do instrumento ficam nos testes offline. Registrar faltas de
   cobertura e custo de coleta disponível, sem inferir ganho de desempenho.

Orçamento operacional inicial: até 90 minutos de execução integrada, reservando
15 para encerramento, e no máximo três inícios identificados. Esses tetos não são
tamanho amostral nem ordem para consumir todas as tentativas. Não repetir até obter
resultado favorável; uma correção exige causa registrada e destino novo dentro do
limite. Desenvolvimento, leitura e CI não são janelas de medição.

Antes de qualquer ensaio no notebook, avisar a janela crítica, conferir tomada,
concorrência de containers e margem do host. Manter as guardas de 5 GiB na entrada
e 2 GiB durante execução; se não houver margem, preparar comando único para execução
com aplicativos fechados. Encerrar o ambiente próprio, preservando artefatos e
volumes. Não reiniciar Docker/WSL nem remover recursos históricos automaticamente.

Preparação, correções pequenas, testes e análise seguem sem aprovação a cada passo.
Pausar diante de necessidade de alterar a aplicação/contrato, condição insegura,
nova despesa/destino externo, mudança relevante do desenho ou esgotamento do teto.
Não pausar apenas por um resultado negativo interpretável.

O mesmo script pode ser iniciado pelo executor ou manualmente. Uma execução manual
não se torna mais válida por sua forma de início. Ensaio exploratório permanece
exploratório; uma avaliação comparativa futura requer protocolo congelado antes
da coleta. Não repetir tudo como confirmação nem reclassificar pilotos depois.

### Critério de continuidade e entrega

Entregar uma matriz curta **questão → sinal atual → lacuna → mecanismo mínimo →
evidência → limite**, procedimento executável quando houver ensaio e uma decisão:

Declarar o denominador da cobertura: eventos conhecidos e marcos esperados, incluindo
identidades que atravessam persistência e publicação posterior. Separar ausência de
marco, conflito de identidade, erro de coleta e resultado funcional. Se houver
exportação, registrar sua saúde e eventuais descartes/retries. O próprio trace não
substitui a confirmação funcional independente. Uma perturbação real, como parar
Notifications, permanece candidata posterior; não integra o primeiro ensaio saudável.

- **Aprofundar:** existe informação nova sobre uma fronteira relevante, com
  correlação verificável e custo compatível; propor comparação própria somente
  se isso responder a uma questão adicional concreta.
- **Manter como complemento:** a organização dos sinais melhora a leitura, mas
  não acrescenta diagnóstico suficiente para uma avaliação independente.
- **Encerrar a exploração:** a informação já está disponível ou o custo/alteração
  necessária supera o ganho. Preservar o achado sem fabricar uma vantagem.

Não criar outro relatório extenso antes desse resultado. README apenas aponta o
estado; DESIGN conserva contratos; este plano registra progressão e decisão.

### Descoberta inicial, somente leitura

Na referência da aplicação `9e3a135a`, `config.py` declara `otel_enabled` e valida
o endpoint; `pyproject.toml` não lista o SDK/exportador OTel e não foi localizada
inicialização de tracing. O flag não implementa telemetria sozinho.
[`messaging/telemetry.py`](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/messaging/telemetry.py)
já emite IDs, serviço, etapa, resultado, UTC e duração. Isso justifica começar
por cobertura dos registros antes de acrescentar um backend. Não foi executado
novo ensaio integrado ou validado tracing nesta branch.

A inspeção estrutural das nove tentativas nos três pacotes encontrou diário de admissão, registros
correlacionados do Core worker, tempos HTTP do observador e amostras de recursos
do instrumento. Não houve recálculo dos resultados nem nova auditoria dos dados
brutos. A cobertura inicial orienta a próxima implementação:

| Fronteira | Sinal disponível | Lacuna a verificar |
| --- | --- | --- |
| Oferta e aceite | `admission.jsonl` | Resposta de aceite não é conclusão de negócio |
| Processamento Core | `worker-attribution.json`, IDs, UTC e duração local | Não cobre sozinho conclusão de Tracking/Notifications |
| Consulta do observador | `http-timings.json`, relógio monotônico e IDs HTTP | Duração HTTP não isola espera no servidor, banco ou agendamento do cliente |
| Confirmação funcional | `events.json` e `observations.jsonl` | Registro observado não equivale ao instante do commit |
| Custo do instrumento | `series.jsonl`, CPU/RSS e memória | Amostragem não prova overhead causal nem captura todos os processos breves |

A correlação offline abaixo cobre essas fronteiras. A captura prospectiva deve
preencher as lacunas identificadas antes de justificar instrumentação adicional.

Os timestamps também exigem leitura do contrato: no resultado aplicado,
[`tracking/message_handler.py`](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/tracking/message_handler.py)
usa `result.decided_at` para criar o evento e relógio local para finalizar a inbox.
Esses instantes não são automaticamente o horário do commit ou da confirmação HTTP.
A [propagação de contexto do OpenTelemetry](https://opentelemetry.io/docs/concepts/context-propagation/)
orienta a correlação entre fronteiras; IDs existentes não são prova de spans
propagados. Mudanças de instrumentação precisam ser avaliadas como nova referência.

### Correlação implementada e próxima verificação

O [extrator offline](scripts/observability_discovery.py) verifica hashes dos ZIPs e
relaciona o primeiro evento preparado de cada tentativa, independentemente do
resultado. O [resumo reproduzível](docs/evidence/observability/discovery-01.json)
preserva fontes, referências, hash do extrator, IDs, relógios originais e lacunas.
A seleção é ilustrativa: não estima a distribuição de atrasos nem substitui a
análise das nove tentativas completas.

Nos nove eventos selecionados, foi possível ligar admissão, registro `DONE` do
Core, confirmações de Tracking/negócio/Notifications e intervalos HTTP. As 54
consultas GET têm IDs diferentes do aceite; a ligação exige também a identidade
do evento e sua pasta de observação. Isso demonstra correlação dos registros
selecionados, não propagação de trace. Não foram isolados os instantes de commit
de Tracking/Notifications nem a espera completa entre publicação e recepção durável.

| Questão | Achado e próximo mecanismo mínimo | Limite |
| --- | --- | --- |
| Relacionar aplicação e observador | IDs existentes permitem a ligação; extrator rejeita identidades conflitantes | Nove exemplos selecionados, sem inferência de latência ou cobertura global |
| Localizar etapas além do Core | Capturar prospectivamente logs já emitidos pelos três workers, junto dos registros do observador | Os pacotes anteriores preservam atribuição Core, não todos os logs de etapas |
| Separar persistência e confirmação | Declarar semântica dos logs e conferir estado funcional independentemente | Log após commit não fornece o instante exato do commit |

Na referência congelada,
[`messaging/worker.py`](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/messaging/worker.py)
emite o resultado de processamento após sair da transação. Em
[`messaging/amqp.py`](https://github.com/campos-labs/fulfillflow/blob/9e3a135a00db218643633c7165d3106f0c8285e1/src/fulfillflow/messaging/amqp.py),
a recepção é registrada após persistência e ACK; a publicação, após confirmação
do broker e registro local. Esses sinais justificam testar a captura existente
antes de acrescentar SDK/backend. Não são spans nem medições exatas de cada espera.

Para reproduzir somente a leitura, em um destino novo, sem Docker ou Azure:

```powershell
uv run --frozen python scripts/observability_discovery.py --output artifacts/observability-reading-01.json
```

O extrator não sobrescreve resultados. Testes cobrem conflitos de identidade,
marcos ausentes, erro HTTP recuperado, falha de transporte, intervalos inválidos,
integridade dos pacotes e preservação da classificação funcional original.

**Primeira preparação integrada executada; fluxo interrompido antes do envio.** A primeira checagem
com aplicativos abertos encontrou 2,11 GiB livres e recusou o início. Após reinício,
parada do nó histórico e fechamento dos aplicativos, o diagnóstico manual sem carga
registrou mínimo de 5,55 GiB em 60 segundos. Isso atende à entrada naquele momento;
não comprova margem durante um ensaio nem efeito causal de desligar a rede.

O executor `scripts/Invoke-ObservabilityPilot.ps1` dá 45 segundos para fechar os
aplicativos, confere novamente as guardas e cria `fulfillflow-observe-01`, com dados
próprios. Reutiliza o bootstrap e a imagem congelada, com uma réplica por processo;
a nova identidade não altera os nomes anteriores. O fluxo envia um evento único,
sem duplicata intencional, falha injetada, KEDA ou tracing. Registra confirmação
funcional, consultas e projeções permitidas dos logs dos três workers; preserva
UIDs e contagens de reinícios para detectar mudança durante a observação.

A entrada exige 5 GiB; o supervisor verifica 2 GiB e tomada durante preparação e
fluxo, a cada dois segundos. Os limites de bootstrap/fluxo são 45/15 minutos, com
encerramento posterior; o total fica dentro do teto inicial de 90 minutos. Destino
ou cluster existente é recusado. Não há repetição automática. O nó novo é parado
no encerramento e os volumes são preservados. O flag `complete` indica término
do procedimento; a cobertura e o valor diagnóstico exigem análise dos registros,
mesmo se o evento foi confirmado. Ausência de registro não prova falta de trabalho.

```powershell
& ./scripts/Invoke-ObservabilityPilot.ps1
```

Manter Docker, tomada e internet durante a preparação, pois alguma imagem pode
precisar ser baixada. O resultado fica em `artifacts/observability-pilot-01`;
credenciais/kubeconfig ficam fora do Git, em
`$env:LOCALAPPDATA/FulfillFlowInfra/observability-01`. Falhas devem ser examinadas
antes de outra tentativa; não apagar a pasta ou o lock para forçar repetição.
OpenTelemetry permanece candidato se os logs deixarem uma lacuna de tracing.

A tentativa `observability-pilot-01` concluiu o bootstrap, mas o fluxo parou com
`WORKER_NOT_STABLE` antes de criar o observador ou enviar o webhook. O menor valor
amostrado foi 2,96 GiB no bootstrap e 3,53 GiB na fase de fluxo, acima da guarda
operacional; o nó foi parado. O registro inicial não preservou qual worker falhou
na prontidão, portanto não determina a causa da indisponibilidade.

A correção aguarda no máximo 120 segundos por três leituras prontas e estáveis dos
workers e preserva seus estados de inicialização. Isso trata uma condição transitória
possível sem presumir que ela foi a causa histórica. `-Resume` aceita exclusivamente
a tentativa anterior à oferta da referência `e1a4624`, conferindo a ausência de
arquivos do evento, identidade do bootstrap e nó parado. Reutiliza o ambiente próprio
e cria `observability-pilot-02`; não refaz bootstrap nem sobrescreve a primeira pasta.
Qualquer início possível de evento impede essa continuação. A nova execução ainda
precisa conferir as guardas, sem baixar limites para executá-la com o editor aberto.

```powershell
& ./scripts/Invoke-ObservabilityPilot.ps1 -Resume
```

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
