# FulfillFlow Infra — Plano de entrega

## 1. Estado atual

**Piloto integrado concluído; pausa de reavaliação na branch `feature/v1.1-autoscaling-kind`.**
Base: v1.0.0, commit `cb6113e6bbd601a65ee5142de85cadc5bf6ba29d`.
CI da branch habilitada. Bootstrap dedicado e smoke do instrumento concluídos;
calibração com uma e duas réplicas executada, com uma oferta não realizada.
Calibração 05 conferida: 300/300 eventos no prazo em cada condição, distribuição
143/157 com duas réplicas e 620 checksums íntegros. Não comprova ganho de escala.
Piloto KEDA `keda-pilot-04` concluído, mantendo uma réplica neste perfil.
Pausa atingida antes de qualquer comparação formal. Sem nova tag, AKS ou ACR.

### Preparação conferida e próximo passo

- Cluster exclusivo `fulfillflow-scale-01`, bancos/credenciais próprios; histórico parado.
- Bootstrap local: `artifacts/scale-bootstrap-01/bootstrap.json`. Migrations e seis
  Deployments prontos. Docker recuperou sem reset; nó novo usa `restart=no` e termina parado.
- Smoke local: `artifacts/scale-instrument-smoke-02/fixed-1/summary.json`: três eventos
  no prazo, efeitos conferidos e pendência final zero. Não demonstra efeito de escala.
- Primeiro smoke parou na identificação OCI, antes da carga. Corrigida distinção
  entre índice Docker `582a858d…`, manifest amd64 `ffb7d2d4…` e config `cc882fab…`:
  referências da mesma imagem importada, vinculada ao SHA congelado da aplicação.
- Retomada: `scale-calibration-01` e `02` pararam antes da carga (API e túnel
  na reinicialização); esperas limitadas corrigidas. `03` ofereceu 300 eventos e
  recebeu 300 respostas 202, mas seu resumo omitiu as últimas 14 respostas por
  corrida de leitura no fechamento. Série inválida como resultado de calibração;
  registros originais preservados. O executor agora exige o marcador final do
  gerador antes de encerrar a observação. Nenhuma dessas falhas comprova perda.
- `scale-calibration-04` executou as duas condições: 1 réplica com 300/300 ofertas
  aceitas e concluídas no prazo; 2 réplicas com 299/299 aceitas e concluídas no prazo,
  mais uma oferta planejada não realizada (`GENERATOR_LIMIT`). Pendência final zero
  em ambas. O resumo geral permanece `complete=false` pela guarda de completude;
  não interpretar como falha dos eventos aceitos. Essa causa reúne atraso da agenda
  ou concorrência cheia; o registro atual não permite separar os dois mecanismos.
  Cluster parado e volumes preservados. Não repetir automaticamente: revisar custo
  do gerador/observador e o diagnóstico de oferta antes de decidir nova execução.
- Smoke do instrumento revisto: `artifacts/scale-instrument-smoke-04`, quatro
  eventos por condição, conclusão e atribuição completas. Na condição de duas
  réplicas, os quatro registros pertencem a um único pod: o instrumento distingue
  prontidão de participação, sem exigir distribuição artificialmente equilibrada.
  Coleta independente abaixo de 0,32 s por ciclo nesse smoke; não extrapolar para
  a carga de 300 eventos. `smoke-03` parou antes da carga ao detectar pod anterior
  ainda em encerramento; adicionada espera limitada antes da preparação.
- Calibração `scale-calibration-05` concluída e conferida. Duas réplicas
  participaram do processamento, sem demonstrar ganho no perfil observado.
  Não agregar tempos das calibrações anteriores como comparação homogênea.
  A revisão autorizou a preparação KEDA delimitada abaixo.
- Comando de referência no [guia Kubernetes](k8s/README.md#calibracao-de-concorrencia):
  300 eventos por condição, 1 depois 2 réplicas; 15 s a 2/s, 30 s a 8/s e 15 s a 2/s.
  Prazo funcional 60 s após aceite observado, observação 120 s por evento,
  concorrência HTTP 8 e consultas até 16. Preparação das entidades fora da oferta.
- O teto operacional da janela preparatória não define tamanho amostral.
  Não aumentar carga para forçar benefício nem alterar a aplicação congelada.
- Preparação KEDA: `artifacts/keda-preparation-03`, infraestrutura `e1a95c0`.
  Consulta saudável com valor zero, três observações de indisponibilidade durante
  falha SQL deliberada e retorno da consulta saudável. HPA registrou
  `FailedGetExternalMetric` e uma réplica durante a falha. A última condição HPA
  ainda refletia o erro anterior; comprova-se retorno da métrica, não o instante
  de reconciliação posterior do HPA. Nenhum evento de negócio oferecido.
  ScaledObject/HPA removidos antes de restaurar uma réplica; nó parado e volumes
  preservados. `01` interrompida por namespace imposto ao bundle; `02` na alteração
  da consulta. Corrigidos namespaces e aplicação declarativa uniforme.
  Tentativas preservadas, sem resultados de autoescalonamento sob carga.
- `keda-pilot-01` interrompido antes da carga: espera de prontidão KEDA
  expirou após 240 s. Instalação subsequente completou; causa específica não
  determinada pelo diagnóstico original. Nenhum evento oferecido, nó parado e
  volumes preservados. Executor agora identifica o Deployment e preserva seu
  estado e o dos pods quando a espera falha, sem expor configuração de secrets.
- `keda-preparation-04` concluiu nova partida e teste de falha/retorno da métrica
  sem carga, com executor `0db58d7`. Retomar em `keda-pilot-02`, mantendo `01`
  intacto. A aprovação da preparação não comprova desempenho nem escala sob carga.
- `keda-pilot-02` parou antes da carga. O diagnóstico preservou ambos os
  componentes KEDA em `CrashLoopBackOff`, com `back-off 5m0s`, superior à espera
  de prontidão de 240 s. A espera passa a 420 s por Deployment, sem alterar
  probes, recursos, carga ou política. Isso corrige a incompatibilidade entre
  prazos; não determina a causa dos reinícios (último exit 255/Unknown).
  Sucessora: `keda-pilot-03`; manter anteriores intactas. Validar sem outros
  containers ativos, inclusive o cluster histórico que pode voltar no reboot.
- `keda-pilot-03`: diagnóstico identifica `ImagePullBackOff`, falha DNS de
  `ghcr.io` no resolvedor Docker durante consulta ao registry. Imagens oficiais
  estavam com `Always`; usar `IfNotPresent` com os mesmos digests preserva a
  identidade e permite reutilizar o cache. Não atribuir retrospectivamente essa
  causa às tentativas sem esse registro. Sucessora: `keda-pilot-04`.
- `keda-pilot-04` concluído, infraestrutura `3da855d`, aplicação congelada.
  Mesmos 300 eventos aceitos e concluídos dentro de 60 s, efeitos e atribuição
  conferidos; uma réplica processou todos. Nenhuma pendência elegível ao final.
  Consulta de escala disponível nas 85 observações de carga/pós-carga, sempre
  zero mensagens elegíveis com idade de pelo menos 5 s. Durante a carga,
  maior idade elegível amostrada de 0,437378 s. Nas 70 amostras pós-carga,
  HPA manteve uma réplica desejada/atual; a última condição foi `ValidMetricFound`.
  A falha deliberada anterior à carga permanece em protocolo separado.
  Fontes: `adaptive/summary.json`, `adaptive/series.jsonl`, `metric-availability.json`,
  `post-load.json`, `metric-fault-probe.json` e `shutdown.json` no pacote local.
- Pausa: integração funcional e observação da política confirmadas neste perfil;
  acionamento 1→2→1 e vantagem de capacidade não demonstrados. Decidir se o
  não acionamento encerra o recorte, se o sinal exige revisão fundamentada ou se
  há justificativa para outro perfil previamente definido. Não aumentar carga
  nem reduzir limiar automaticamente. Piloto não vira repetição comparativa.

A v1.0.0 permanece encerrada: aplicação v1.3.0-rc.1 congelada, configuração saudável
conferida e laboratório parado, com dados e evidências preservados. Resultados e
protocolos pertencem à [avaliação operacional](docs/OPERATIONAL_EVALUATION.md).
O [DESIGN](DESIGN.md) define contratos; o [guia Kubernetes](k8s/README.md), comandos.
Este plano registra entregas e decisões, sem repetir resultados ou diário de execução.

## 2. Referência concluída e limites preservados

| Entrega v1.0.0 | Alcance |
| --- | --- |
| Ambiente e operação | Kind isolado, aplicação congelada, persistência, verificação e restauração delimitada de um workload |
| Avaliação | Comparação de 20 tentativas; protocolo separado com seis pendências e três inconclusões. Pilotos e séries interrompidas excluídos |
| Documentação e evidências | Relatório, registros selecionados e dois pacotes completos versionados, com origem e hashes |

A [release v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0)
identifica o fechamento; SHAs executados e CIs constam no relatório. O
[registro anterior à consolidação](https://github.com/campos-labs/fulfillflow-infra/blob/47dbd111ad4eff89a8e64c7b50d7d2c59c23baf7/RELEASE_PLAN.md)
preserva o histórico, sem tornar vigentes seus comandos e propostas antigas.

Os ZIPs publicados permitem conferir downloads por hash, mas não comprovam
restauração de bancos/volumes após perda do equipamento. Pilotos e séries
interrompidas permanecem locais, com exclusões documentadas. Seletores de
NetworkPolicies foram validados; tráfego permitido/bloqueado não foi ensaiado.
Capacidade, estabilidade prolongada e HA não foram avaliadas.

Não repetir séries concluídas, ampliar seus denominadores ou substituir registros
interrompidos. A extensão terá protocolo, dados e destinos próprios. Seu resultado
não modifica retrospectivamente o aceite, as imagens ou as evidências da v1.0.0.

## 3. Incremento de viabilidade em Kind

### Objetivo e decisões de entrada

Avaliar se uma política de réplicas pode melhorar o atendimento à demanda com
recursos controlados. As perguntas operacionais são:

- Como réplicas fixas e autoescalonamento diferem na conclusão dentro do prazo e no uso de recursos?
- O sinal de escala representa o trabalho que o workload ainda pode processar?
- A redução de réplicas preserva a conclusão do trabalho aceito?

O piloto verifica se essas perguntas podem ser respondidas; não exige ganho mínimo
nem resultado favorável. Análises compartilhando execuções não contam como
repetições independentes. Os contratos do alvo estão no [DESIGN §8.7](DESIGN.md#87-alvo-de-autoescalonamento-em-kind).

| Decidido para a extensão | A resolver no piloto |
| --- | --- |
| Kind, um workload e capacidade de nós fixa; aplicação congelada | Worker elegível, gargalo e margem efetiva do host |
| Calibração inicial com uma e duas réplicas; mínimo de uma na política | Sinal, consulta/exportador, limiares e estabilização |
| KEDA e Locust preferenciais; coleta temporal obrigatória, Prometheus preferencial | Versões compatíveis fixadas, instalação e custo da coleta |
| Evidências por evento separadas da telemetria agregada | Perfil de entrada, prazo funcional e janela de observação posterior |
| AKS opcional, sem recursos Azure neste incremento | Comparação futura e necessidade de verificação complementar na nuvem |

Não selecionar Notifications apenas por ter sido o alvo da restauração. Inspecionar
processamento, concorrência e pendências dos workers da referência; escolher um
alvo justificável. Não adicionar atraso artificial, alterar regra de negócio ou
mudar limites/pools para fabricar vantagem. Se a referência exigir alteração na
aplicação para permitir escala correta, apresentar a incompatibilidade e pausar.

### Entrega em um incremento, com verificações desde o início

| Sequência | Entrega verificável |
| --- | --- |
| Preparação | Conferir recursos locais e contratos do alvo; habilitar a CI nesta branch, hoje restrita a push em main; fixar ferramentas novas e preparar instalação/encerramento reproduzíveis em ambiente dedicado |
| Instrumento | Gerador com oferta controlada e observação independente; coleta temporal e registros por evento; configuração validada, limites, identificação e testes de falha do instrumento |
| Calibração | Verificar uma e duas réplicas com o mesmo perfil de entrada, coleta e configuração por réplica; registrar contenção, conexões, pendências e resultados antes de ativar a política |
| Política e piloto | Implementar a política mínima se sinal e margem forem suficientes; verificar aumento/redução e falha de métrica; exportar evidências, encerrar o ambiente e parar para reavaliação |

Resolver ajustes rotineiros sem abrir novos incrementos. Fixar antes de cada
execução SHA, configuração, IDs, limites e critério de encerramento. A primeira
janela integrada será limitada a 120 minutos, reservando 20 para observação final,
exportação e parada; nenhuma carga deve continuar sem supervisão além do prazo.
Até três execuções identificadas de calibração/piloto cabem nessa janela, sem
reposição automática. Correção do instrumento exige nova identidade e registro
do motivo; resultados anteriores permanecem preservados e fora de agregação.

Reutilizar interfaces e verificações pertinentes, sem alterar o comportamento dos
executores encerrados. Testar o que mudar: configuração inválida, classificação
por evento, consulta falha, métricas ausentes/obsoletas e limites. Validar manifests,
permissões de leitura, ownership da escala e encerramento; usar PostgreSQL,
RabbitMQ e Kubernetes reais no piloto. Mocks complementam, não substituem esse aceite.

Carga e observação não compartilham uma espera que reduza silenciosamente a oferta.
Registrar oferta planejada/realizada, recusas, aceite desconhecido e saturação do
gerador. O piloto deve oferecer um perfil curto de subida, patamar e queda, limitado
por taxa e quantidade total de eventos; parâmetros ficam registrados antes da execução.
Prazo funcional e observação posterior são calibrados aqui e congelados antes de
qualquer comparação formal. Não usar resultados do piloto como repetições dessa comparação.

### Critérios da pausa

A entrega de viabilidade deve permitir revisar, em conjunto:

1. **Alvo e sinal:** worker escolhido, etapa observada e relação da métrica com
   pendências conferidas por registros da aplicação, incluindo limites da consulta.
2. **Execução real:** identidades das réplicas exercitadas, uma versus duas e,
   quando viável, subida/descida automáticas com configuração efetiva registrada.
3. **Correção:** resultado esperado por etapa, trabalho aceito acompanhado após
   redução, efeitos sem duplicação indevida e ausência de reenvio/rearme automático.
4. **Medição:** série temporal alinhada ao registro por evento, lacunas explícitas,
   custo da instrumentação e distinção entre prazo excedido e observação inconclusiva.
5. **Operação:** ausência de controladores concorrentes, tratamento demonstrado de
   falha da métrica, exportação com hashes e parada confirmada sem excluir volumes.

A falta de ganho não é falha do piloto. Pausar antecipadamente se não houver
margem de recursos, sinal utilizável, concorrência correta ou necessidade atendível
sem mudar a aplicação. Não insistir em aumentar carga ou instalar alternativas
sucessivas para obter um resultado favorável. Registrar o diagnóstico disponível.

No encerramento, atualizar o estado deste plano com SHA/CI, localização das evidências,
checks executados e limitações; não criar documento de contexto adicional nem
incorporar o piloto ao relatório fechado da v1.0.0. A decisão será **continuar,
ajustar o recorte ou encerrar a extensão**, sem pressupor a próxima etapa.

### Janela executada — piloto mínimo KEDA

Uma preparação sem carga e um piloto identificado, sem repetição automática.
KEDA 2.20.2 core com versões/hashes fixados, consulta de mensagens elegíveis com
idade mínima de 5 s, alvo de uma por réplica, mínimo 1 e máximo 2. O DESIGN detalha
limites, cadências e encerramento; não mudar perfil de 300 eventos nem prazo 60 s.
O teste de falha altera somente a consulta do scaler e restaura a configuração.
Execução de carga fica separada, seguida de 360 s de observação sem novas ofertas.

Distinguir leituras válidas sem demanda suficiente, indisponibilidade da métrica e
réplicas efetivamente observadas. Permanecer em uma réplica é resultado admissível.
Registrar subida/descida somente se ocorrerem; não fabricá-las para satisfazer aceite.
O relatório de calibração 05 e seus arquivos permanecem intactos. O piloto formou
conjunto próprio e terminou na pausa de reavaliação, antes de comparação formal.

### Reavaliação do limite observado

A viabilidade de concorrência e integração foi demonstrada; necessidade e benefício
de escala continuam em aberto. Na calibração 05 duas réplicas processaram 143/157
eventos; no piloto 04 uma concluiu 300/300 no prazo. Ausência de escala não prova
equivalência entre políticas nem ausência de transientes entre amostras.

Diagnóstico retrospectivo concluído em `artifacts/scale-diagnostic-01/review.json`,
com hashes dos 305 arquivos de entrada. Reprodução: `scripts/review_scale_pilot.py`;
saída separada, sem alterar a campanha ou iniciar recursos.

- Durante o patamar, idade elegível amostrada: 0,354; 0,437; 0,224; 0,262;
  0,212; 0,175 s. Contagens: 5, 2, 2, 5, 5, 6. Não aparece envelhecimento
  progressivo; contagens pequenas e oscilantes não demonstram ausência de transientes.
  Nos cinco intervalos inteiramente dentro do patamar, o contador de conclusões
  Core cresceu 197 em 25,109 s (aproximadamente 7,85/s), próximo à oferta de 8/s.
  É ritmo observado nessa janela, não estimativa da capacidade sustentável máxima.
- O observador registrou 2.409 respostas GET, todas 200: oito por evento em 291
  casos e nove em nove casos. Excluídos 900 POSTs de preparação anteriores à
  carga; os 300 webhooks pertencem ao gerador. Contagem não inclui tentativas sem
  resposta não registradas. O rótulo `operation=prepare` de alguns GETs é estado
  herdado do verificador; sua data e método os identificam como observação da carga.
- Correção de interpretação: 14 coletas da API Core contêm apenas seis leituras
  de CPU com timestamps distintos do kubelet. Duas estão próximas de 0,5 CPU
  (limite configurado), repetidas em cinco coletas. O worker tem cinco leituras
  distintas, máximo 0,4133 CPU. Não tratar cinco coletas como cinco ocorrências
  independentes, nem inferir throttling. Os contadores de throttling não foram
  preservados; uma consulta posterior não recupera sua atribuição a esta carga.
- Não houve oferta omitida; atraso máximo de despacho 16 ms e concorrência
  amostrada máxima 5 de 8. Quantidade de GETs evidencia custo potencial de
  observação, sem atribuir a ela uma fração da CPU ou da latência.

Decisão desta revisão: não executar os 540 eventos agora. Não surgiu evidência
suficiente de crescimento de pendência envelhecida para justificar alongar o
mesmo patamar. Se a extensão continuar, a lacuna é uma coleta focal de throttling
por componente e de volume/tempo das consultas, com timestamps da fonte, sob o
perfil já conhecido. Isso antecede caracterizar capacidade ou escolher nova demanda.
Nenhuma coleta adicional foi executada nesta revisão.

Para a eventual coleta focal, medir o custo das consultas e throttling por
componente antes de definir nova carga. Manter app, recursos e política inicialmente;
não reduzir recursos do worker, baixar arbitrariamente o limiar ou mudar alvo para
produzir escala. Separar conclusão funcional de tempo até sua observação. As medianas
entre calibração e piloto não estimam custo causal do KEDA: instrumentação, momentos
e estado acumulado diferem. Não são repetições de uma comparação controlada.

Se o diagnóstico justificar observar demanda sustentada, perfil candidato: 15 s a
2/s, 60 s a 8/s e 15 s a 2/s (540 eventos). Altera somente duração do patamar,
sem subir pico, dentro dos tetos atuais; prazo funcional 60 s permanece. A pergunta
é se a pendência cresce quando a demanda se sustenta, não se conseguimos forçar
1→2. Primeiro caracterizar com uma réplica; testar segunda/política somente se houver
pendência atribuível ao alvo e margem no ambiente. Interromper diante de limitação
do gerador, observação ou outra etapa. Não prosseguir em escalada de taxas se o sinal
continuar curto. Perfil apenas proposto; nenhuma nova execução iniciada nesta revisão.

### Coleta focal de instrumentação

Uma execução identificada, com uma réplica fixa e os mesmos 300 eventos,
recursos, prazos e verificações da calibração. KEDA permanece instalado,
mas ScaledObject/HPA do alvo devem estar ausentes. Nenhuma alteração da
aplicação ou redução do limiar. Não é comparação formal nem
repetição do piloto adaptativo.

Antes de oferecer carga, exigir os três contadores cAdvisor de períodos CFS,
períodos limitados e segundos de throttling nos seis processos da aplicação.
Excluir agregados de pod; preservar identidade do cgroup e timestamp da fonte.
Ausência não equivale a zero; reinícios, timestamps repetidos e resets
impedem interpretar diferenças como intervalos independentes. Coletar a cada
5 s junto da série existente, registrando a duração adicional da coleta.

Cronometrar o transporte das consultas do observador após a preparação,
sem suprimir requisições ou verificações. Buffer por evento, exportado
no encerramento: tempos incluem espera do transporte local, mas excluem validação
posterior e persistência das evidências. Isso não mede CPU causal da observação.
Throttling observado também não prova isoladamente o gargalo global.
Exportar resultados e parar somente o nó dedicado, preservando volumes.
Reavaliar antes de alterar taxa, duração ou recursos.

**Resultado da coleta focal:** `artifacts/scale-instrumentation-01`, instrumento
`3093d9c`, concluída com 300/300 aceitos e concluídos no prazo; atribuição
confirmada a uma réplica, sem pendência elegível final. Nó parado e volumes
preservados. Conferência separada: `artifacts/scale-instrumentation-01-review.json`,
613 hashes verificados; reprodução por `scripts/review_scale_diagnostic.py`.

| Componente | Períodos com throttling / observados | Janela da fonte (s) |
| --- | --- | --- |
| Core API | 406/527 (77,04%) | 58,559 |
| Core worker | 206/586 (35,15%) | 66,062 |
| Tracking API | 70/450 (15,56%) | 58,745 |
| Tracking worker | 112/588 (19,05%) | 66,942 |
| Notifications API | 1/467 (0,21%) | 73,708 |
| Notifications worker | 69/496 (13,91%) | 62,350 |

Janelas usam timestamps distintos por cgroup: cinco ou seis leituras de origem,
sem reset observado, em 14 coletas. Elas diferem entre componentes e podem incluir
bordas da preparação/drenagem. Percentuais representam períodos CFS com
restrição, não CPU perdida, requisições prejudicadas ou indisponibilidade.
Semântica: [cAdvisor](https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md)
e [controle de banda CFS](https://docs.kernel.org/scheduler/sched-bwc.html).

Observador: 2.409 GETs, todos 200; transporte mediano 0,281 s, p95 0,500 s e
máximo 1,187 s (p95 por posto superior). Conclusão observada: mediana 9,828 s,
p95 13,313 s, máximo 14,125 s, incluindo polling e verificações; não é tempo
puro do worker. Coleta completa: máximo 0,735 s; consulta adicional cAdvisor:
máximo 0,188 s; nenhum ciclo excedeu os 5 s. Não demonstra overhead nulo.
Máximos amostrados: quatro pendências elegíveis e idade 0,553917 s.

**Aprendizado e pausa:** o limite de CPU atua em várias etapas, inclusive no
worker, enquanto a carga continua atendida. A hipótese de pressão no Core API
agora tem evidência de restrição, mas a parcela causada pelo observador e o
gargalo global continuam indeterminados. Não concluir que aumentar réplicas
resolveria essa restrição. Não executar 540 eventos nem alterar recursos/limiar
com base apenas nestes percentuais. Antes de caracterizar capacidade, decidir se
vale isolar o custo da observação em um protocolo próprio, preservando todas as
asserções, ou encerrar esta extensão com o limite demonstrado. AKS e comparação
formal continuam fora desta coleta. KEDA permanece preferencial para eventual
continuidade; este diagnóstico fixo não reavalia sua política.

### Avaliação delimitada do observador

A revisão do código identificou duas releituras na observação terminal:
Tracking e Notifications eram consultados na triagem e novamente na validação.
No diagnóstico sucessor, reutilizar opcionalmente somente essas respostas dentro
da mesma chamada de observação. Executar todas as asserções de identidade,
transição, timestamps e resultado; manter consultas de pedido, shipment e efeitos
únicos. Não manter cache entre eventos ou ciclos de polling. Uma observação
terminal passa de oito para seis GETs, além das consultas de espera necessárias.

Uma execução de diagnóstico, mesmos 300 eventos e uma réplica fixa,
sem mudar aplicação, recursos, cadência, prazo ou política. O protocolo registra
`reuse_terminal_reads=true`; o modo anterior continua padrão e as evidências
anteriores não mudam. Não remover fsync, asserções ou efeitos verificados.

Critérios: 300 aceites e conclusões com efeitos/atribuição confirmados,
menos consultas sem falhas de observação, coleta íntegra e encerramento do nó.
Confrontar volume HTTP, tempo de verificação, backlog e throttling apenas como
diagnóstico descritivo: uma execução sucessora sem alternância/repetições
não estima ganho causal nem isola todo o custo da observação. Reavaliar após
essa coleta; não aumentar carga automaticamente.

**Resultado:** `artifacts/scale-instrumentation-reuse-01`, instrumento `12cb801`;
300/300 aceitos e concluídos no prazo, efeitos e atribuição confirmados, sem
pendência elegível final. 613 hashes conferidos; nó parado, volumes preservados.
Conferência: `artifacts/scale-instrumentation-reuse-01-review.json`. Síntese dos
dois diagnósticos: `artifacts/scale-observer-assessment-01.json`; registros locais,
não anexados a uma release.

| Medida | Releituras (`instrumentation-01`) | Reutilização (`reuse-01`) |
| --- | --- | --- |
| GETs do observador, todos 200 | 2.409 | 1.812 |
| Mediana da verificação terminal (s) | 2,2895 | 1,5855 |
| Mediana aceite → conclusão observada (s) | 9,828 | 5,109 |
| p95 aceite → conclusão observada (s) | 13,313 | 6,203 |
| Core API: períodos com throttling | 406/527 | 301/551 |
| Core worker: períodos com throttling | 206/586 | 199/560 |
| Maior idade elegível amostrada (s) | 0,553917 | 0,350512 |

Foram retiradas 600 releituras terminais; consultas adicionais de espera passaram
de nove para doze, resultando em 597 GETs a menos. O teste do instrumento confirma
seis em vez de oito GETs por observação terminal com as mesmas asserções.
A duração terminal começa em `observed_monotonic` da chamada bem-sucedida e
termina após confirmar efeitos. Não inclui toda a espera anterior de polling ou
agendamento dos observadores; medianas de componentes não são aditivas.

**Conclusão delimitada:** menos consultas redundantes e resultado funcional
preservado justificam preferir a reutilização na próxima versão do instrumento.
A queda descritiva dos tempos não mede aceleração da aplicação. A diferença
entre dois ensaios em momentos distintos, com estado acumulado e janelas cAdvisor
diferentes, não estima efeito causal ou significância. Não demonstra que a CPU
do Core API era o gargalo global nem que o custo do observador foi eliminado.
O tempo até confirmação pode ser sensível ao instrumento mesmo com o mesmo
contrato de conclusão. Comparar políticas requer fixar esse instrumento em todas
as condições; resultados anteriores permanecem identificados e separados.

**Próxima decisão:** encerrar os ajustes do observador nesta etapa. Se houver
continuidade, propagar explicitamente o modo validado ao piloto KEDA e definir
uma caracterização curta da capacidade com uma réplica, patamares escolhidos
antes da coleta e interrupção por limites do gerador, observador ou outra etapa.
Isso é mais informativo que prolongar automaticamente 8/s para 540 eventos.
Não definir capacidade máxima nem atribuir benefício de escala a partir destes
ensaios. Taxas novas, recursos, limiar e adoção do modo no KEDA permanecem para
essa decisão; o padrão anterior continua disponível. AKS não resolve a lacuna
atual de caracterização e continua adiado.

### Condições do host e alcance dos diagnósticos

Relato posterior indica atividade interativa concorrente e interrupção de energia/
conectividade durante o período dos diagnósticos. Esses fatores não foram
controlados prospectivamente; a coleta registra processos do instrumento e memória
do host, mas não contabiliza CPU integral de outros aplicativos, frequência,
temperatura ou alimentação durante a carga. Preservar os dados originais e marcar
os tempos/recursos como exploratórios. A redução das releituras é verificável
no instrumento; o tamanho do efeito temporal não pode ser atribuído a ela.

Conferência de 2026-09-26, UTC-03: a série de `instrumentation-01` cobre
15:27:59–15:29:04 e a de `reuse-01`, 15:48:55–15:50:00. Intervalo máximo
entre coletas de ambas: 5,016 s. Eventos Windows consultados entre 15:20 e 16:02
registram `AcOnline=false` às 15:34:00 e `true` às 15:34:02, com transições
de espera/retomada até 15:34:19, fora dessas duas janelas. Isso não demonstra
ausência de interferência do host nem identifica com certeza toda a interrupção
relatada; não há lacuna de dois minutos nas séries analisadas. Os resultados
funcionais preservados permanecem 300/300, sem transformar esses ensaios em
comparação controlada. Registro sanitizado: `artifacts/host-conditions-20260926.json`.

Para novas medições, separar preparação com acesso externo da janela reservada
local. Antes: finalizar downloads/instalações, conferir imagens e dependências,
fechar cargas interativas, manter laboratórios históricos parados e aguardar o
host estabilizar. Registrar perfil de energia, alimentação, recursos Docker e
condições de partida. Reiniciar é opcional; não alterar o perfil de energia
entre condições. Manter tomada e tampa aberta, sem suspensão, builds ou outras
campanhas durante toda a janela, da preparação das entidades à confirmação
do encerramento. Sinalizar explicitamente início e fim ao operador.

Mudança de alimentação, suspensão/reinício ou atividade externa relevante
durante uma coleta destinada à capacidade torna sua comparabilidade temporal
pendente; interromper nova oferta e preservar resultados/encerramento quando
possível. Não apagar nem reclassificar eventos aceitos como perdidos. A decisão
de exclusão/repetição deve constar do protocolo antes da campanha.

A execução fixa usa recursos locais e pode ocorrer pelo PowerShell sem internet
após conferir as dependências; instalação KEDA, imagens ausentes e sincronização
Git exigem etapa conectada. Não desativar/reconectar a rede no meio da medição.
Não repetir toda a história preparatória: usar uma referência limpa com o
observador validado antes da futura caracterização. A reutilização é a escolha
preferida, fixada por protocolo/SHA; correções posteriores exigem nova identificação,
não um congelamento irreversível. Não impor ordem universal entre utilização,
throttling, backlog e drain: a caracterização deve observar esses sinais, sem
exigir que apareçam nessa sequência.

### Referência limpa antes da caracterização

Referência concluída em `scale-clean-reference-02`, após a interrupção
preparatória de `01`: uma réplica fixa e 300 eventos,
`reuse_terminal_reads=true` e `controlled_host=true`. Sem nova taxa, alteração
de recursos, política ou aplicação.

`host-conditions.jsonl` registra a cada segundo alimentação/bateria, CPU
acumulada global e memória disponível. Perfil de energia conferido antes/depois.
Pré-verificação sem confirmação de tomada ou perfil impede iniciar o nó.
Amostra em bateria/desconhecida, perfil diferente/desconhecido, erro do monitor,
intervalo maior que 5 s ou divergência maior que 1 s entre avanços UTC e
monotônico impede qualificar a referência como limpa. Monitoramento é amostrado:
transições breves podem escapar e aplicativo externo não é identificado.

`host-review.json` separa essas condições do resultado funcional. Problema detectado
durante a execução não cancela imediatamente as ofertas; os limites normais de
carga/observação e encerramento permanecem. O resumo final fica incompleto para
esta finalidade, sem apagar conclusões de negócio ou reenviar eventos. Queda abrupta
ainda pode impedir exportação e encerramento: conferir arquivos/estado antes de repetir.

O launcher anuncia janela crítica antes do comando e confirma encerramento somente
com `shutdown.json` indicando nó parado. A janela inclui preparação e exportação,
não apenas os 60 s de oferta. O operador reserva o host antes de executar. Após
essa referência, revisar oferta/aceite/conclusão, observador e host; então definir
patamares de caracterização. Não executar campanha formal automaticamente.

A tentativa `scale-clean-reference-01` parou na pré-verificação com
`THROTTLING_METRIC_UNAVAILABLE_notifications`, antes de criar `fixed-1` ou preparar/
oferecer eventos. Host validado nas amostras (94 registros; intervalo máximo 1,016 s),
nó parado e volumes preservados. Não é resultado funcional nem falha de negócio.
O registro original não preservou a exposição parcial cAdvisor; causa exata não
confirmada. Compatível com indisponibilidade transitória na inicialização, não
prova defeito de Notifications ou efeito da alimentação.

Ajuste do instrumento: antes de qualquer preparação funcional, aguardar até 90 s
pela presença dos três contadores nos seis componentes, consultando a cada 5 s
(além do tempo de cada consulta, limitada a 10 s). Registrar cada ausência em
`throttling-startup.jsonl`. Repetir somente indisponibilidade de métrica nessa etapa;
valor inválido e erro de comando continuam interrompendo. Durante a carga, a coleta
mantém a validação estrita, sem espera adicional, preenchimento com zero ou omissão
de componentes. A referência sucessora foi `scale-clean-reference-02`.

Verificação isolada de pré-requisitos em `throttling-startup-check-01`:
12 consultas com ausências transitórias e a 13ª com os seis componentes
presentes, após 61,516 s de espera. Nenhum evento preparado ou oferecido; nó
parado e volumes preservados. Confirma que a espera resolve a disponibilidade
nessa inicialização, sem identificar a causa interna da exposição parcial nem
substituir a referência controlada. Validação do ajuste: 204 testes aprovados,
Ruff e verificação documental aprovados.

### Resultado da referência controlada

`scale-clean-reference-02`, instrumento `0795436`, manteve a referência da
aplicação e o digest de configuração registrados no protocolo. Conferência
local: `artifacts/scale-clean-reference-02-review.json`, 616 arquivos com hashes
válidos. Originais preservados; estes pacotes continuam somente locais.

| Medida | Resultado |
| --- | --- |
| Ofertas / aceites / conclusões no prazo | 300 / 300 / 300 |
| Atribuição | Uma réplica; sem reinício entre as conferências |
| GETs do observador | 1.812; todos HTTP 200 |
| Aceite → confirmação observada | Mediana 5,125 s; p95 6,234 s |
| Pendências elegíveis / idade máxima amostradas | 8 / 0,650 s |
| Inbox ao final | Zero elegíveis, em retry ou bloqueadas |
| Core API: períodos com throttling | 318/726 (43,80%), janela 79,101 s |
| Core worker: períodos com throttling | 141/620 (22,74%), janela 67,696 s |
| Host | 191 amostras válidas; maior intervalo 1,031 s; plano preservado |
| Encerramento | Nó parado, volumes preservados |

A espera inicial resolveu a ausência de métricas em 5,219 s nesta execução.
As 14 coletas não excederam a cadência; atraso máximo de despacho de 0,015 s.
Durante as seis observações internas ao patamar de 8/s, o contador de conclusões
avançou aproximadamente 7,870/s. Pendências oscilaram de 4 a 8 e terminaram em
7 nesse recorte; idade entre 0,392 e 0,650 s, sem crescimento monotônico. Os picos
amostrados de CPU foram 0,491 no Core API e 0,288 no worker. Essas amostras não
medem capacidade máxima nem isolam um gargalo; throttling não equivale a essa
fração de CPU perdida. O controle amostrado do host não prova exclusividade.

**Decisão:** referência suficiente, sem repetir o mesmo perfil. Uma réplica
atendeu esta demanda; a coleta fixa não testa KEDA nem demonstra benefício de
escalar. Encerrar ajustes do instrumento e definir a caracterização curta antes
da próxima carga. Manter observador, recursos e réplica; variar somente demanda
predefinida, com limites para gerador, observação e host. A proximidade do Core API
ao limite torna especialmente importante distinguir pressão da entrada/consulta
de acúmulo no worker. Não reduzir o limiar KEDA, adotar AKS ou executar
comparação formal com base nesta referência.

### Depois da pausa — ainda não autorizado

Uma comparação formal constitui um segundo incremento, se aprovada. Antes da
coleta, congelar condições, perfil de entrada, preparação, prazo, repetições,
ordem e exclusões. Escolher uma referência fixa justificável: fixo em uma réplica
versus adaptativo mistura automação com recursos adicionais; fixo no máximo
versus adaptativo responde a outro compromisso entre atendimento e recursos.
Não abrir automaticamente três condições nem atribuir toda diferença ao controlador.

Manter instrumentação equivalente entre condições. Registrar totais por tentativa;
eventos da mesma execução não substituem repetições independentes. Benefícios,
equivalência, piora e limites são resultados admissíveis. Uma candidata funcional
poderá receber `v1.1.0-rc.N`; esta preparação não publica tag nem garante release.

<a id="3-extensões-possíveis"></a>

## 4. Opções para reavaliação

### AKS e ACR — complemento opcional

Kind permanece o ambiente principal da extensão. AKS pode verificar a mesma
referência e cenários selecionados de escala/conclusão, com nós fixos, sem repetir
a comparação completa. Exige espaço efetivo para réplicas adicionais: uma
implantação sem essa margem comprova apenas o que foi funcionalmente exercitado.
Dados de nuvem formam conjunto separado; não transferir tempos/capacidade Kind
para AKS nem comparar uma condição local com outra na nuvem. ACR pertence à
implantação Azure, não ao requisito da avaliação local.

A preparação e as consultas anteriores não estabeleceram configuração provisionável.
Antes de qualquer apply, reconferir assinatura, região, quotas, restrições de SKU,
capacidade, acessos, orçamento e custos residuais. Validar o plano e as guardas do
[guia Terraform](infra/README.md); quota positiva não garante alocação. Expansão de
nós e custos da nuvem constituiriam outro recorte, não parte desta escala de pods.

### Capacidades condicionadas a uma lacuna concreta

| Capacidade | Critério para adoção |
| --- | --- |
| Grafana | Visualização útil da coleta já exportável; não condição para validar o piloto |
| OpenTelemetry | Pergunta de diagnóstico não respondida pelos sinais existentes; possível extensão própria, com custo e cobertura de instrumentação avaliados |
| Segurança na CI | Lacuna identificada após conferir os checks existentes; distinguir código, dependências e imagens, sem mudar silenciosamente a aplicação congelada |
| Argo CD / GitOps | Avaliação de reconciliação e drift, com responsabilidade de mutação revisada para não disputar com restauração/escala |
| Alertmanager, Litmus ou blue/green | Somente se uma nova pergunta exigir alertas, mecanismo de falha ou estratégia de implantação diferentes |

Terraform e GitHub Actions integram preparação/validação; isso não comprova deploy
Azure executado. Helm pode instalar componentes auxiliares sem substituir o
Kustomize existente. Não adotar outro gerador de carga nem uma plataforma completa
de observabilidade apenas para ampliar ferramentas. Novas extensões não são
requisitos para concluir a recuperação ou o piloto de escala.

## 5. Versionamento e método de trabalho

As versões da infraestrutura são independentes das versões da aplicação. A v1.0.0
fixa comandos, configuração e formatos de saída suportados. Correções compatíveis
incrementam PATCH; capacidades compatíveis, MINOR; mudanças incompatíveis, MAJOR.
Candidatas usam `-rc.N`. Não alterar referências publicadas ou SHAs executados.

Desenvolver a extensão em `feature/v1.1-autoscaling-kind`, sem branch por condição
ou tentativa. Integrar na main somente após aceite da extensão; a v1.0.0 continua
acessível pela tag. AKS terá branch quando iniciado, a partir da referência que
for verificar; não reservar sua versão agora. PRs e Issues não são requisito do fluxo.

1. Ler os contratos pertinentes do DESIGN e o estado deste plano. Preservar a
   aplicação e as evidências congeladas; não alterar runtime para acomodar resultado.
2. Resolver ajustes rotineiros no incremento autorizado. Mudanças de contrato,
   ambiente, custo, acesso ou persistência exigem decisão específica e plano concreto.
3. Revisar e validar por assunto antes de commit/push na branch ativa. A CI da
   aplicação permanece no repositório de origem; sua aprovação não valida esta extensão.
4. Manter comandos utilizáveis em PowerShell. Conferir executáveis e versões;
   não alterar ferramentas do operador ou PATH silenciosamente.
5. Validar configuração antes de mutação, com contexto, identidade e propriedade
   dos recursos explícitos. Falha de permissão não autoriza administração global.
6. Toda operação tem prazo, diagnóstico e encerramento. Parar na primeira falha
   inesperada; reconciliar resultado incerto antes de qualquer retomada, sem apagar registros.
7. Cobrir comportamento alterado com checks pertinentes. Documentação sem runtime
   exige revisão de links, exemplos, dados, fronteiras e diff; não repetir campanhas.
8. Não versionar secrets, kubeconfigs, planos/state Terraform, dumps ou caminhos
   pessoais. Saídas operacionais só entram em pacotes delimitados, revisados para
   compartilhamento e com hashes; dados derivados identificam fonte e transformação.
9. Reportar alterações, checks, SHA e limitações. Fornecer comando manual somente
   para operação preparada, necessária e autorizada. Evitar documentos redundantes.
