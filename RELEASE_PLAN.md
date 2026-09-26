# FulfillFlow Infra — Plano de entrega

## 1. Estado atual

**Incremento de viabilidade em implementação na branch `feature/v1.1-autoscaling-kind`.**
Base: v1.0.0, commit `cb6113e6bbd601a65ee5142de85cadc5bf6ba29d`.
CI da branch habilitada. Bootstrap dedicado e smoke do instrumento concluídos;
calibração com uma e duas réplicas executada, com uma oferta não realizada.
Revisão do gerador pendente antes de repetir ou integrar KEDA.
A pausa final do incremento ainda não foi atingida. Sem nova tag, AKS ou ACR.

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
- Comando de referência no [guia Kubernetes](k8s/README.md#calibracao-de-concorrencia):
  300 eventos por condição, 1 depois 2 réplicas; 15 s a 2/s, 30 s a 8/s e 15 s a 2/s.
  Prazo funcional 60 s após aceite observado, observação 120 s por evento,
  concorrência HTTP 8 e consultas até 16. Preparação das entidades fora da oferta.
- Rever sinal, conclusão, oferta não realizada e folga antes de KEDA. O teto de
  120 minutos e até três execuções limita operação; não define tamanho amostral.
  Completar atribuição por réplica e custos do instrumento antes do piloto integrado.
  Não aumentar carga para forçar benefício nem alterar a aplicação congelada.

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
