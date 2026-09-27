# FulfillFlow Infra — Estado de entrega e evolução

## 1. Estado atual

**Incremento ativo: `feature/v1.3-aks-portability`**, criado da `main` em
`777900d`, referência da `v1.2.0-rc.1`. Esta etapa prepara a verificação de
portabilidade; ainda não realizou descoberta autenticada da nova assinatura,
provisionamento ou ensaio Azure. A configuração concreta e a autorização da
janela operacional ainda precisam ser conferidas.

Observabilidade consolidada na [v1.2.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.2.0-rc.1),
com integração de `feature/v1.2-observability` à `main`, a partir de
`v1.1.0-rc.1` (`92089b8`). O
[relatório técnico](docs/OBSERVABILITY_EVALUATION.md) consolida correlação dos workers,
captura HTTP saudável e sequência controlada 200 → 503 → 200, com limites explícitos.
Dois pacotes e diagramas reproduzíveis permitem examinar os resultados offline.
Não há nova carga necessária para conferir os casos. A [nota da candidata](docs/releases/v1.2.0-rc.1.md)
e a página da pré-release identificam conteúdo, referências e anexos.

| Referência | Entrega |
| --- | --- |
| [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0) | Recuperação em Kind; [relatório](docs/OPERATIONAL_EVALUATION.md) e dois pacotes preservados |
| [v1.1.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.1.0-rc.1) | Comparação fixa/adaptativa concluída, integrada à main; [relatório](docs/SCALING_EVALUATION.md), figuras e três pacotes |
| [v1.2.0-rc.1](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.2.0-rc.1) | Diagnóstico complementar, [relatório](docs/OBSERVABILITY_EVALUATION.md), [dois pacotes](docs/evidence/observability/README.md) e executores versionados |
| Azure | Preparação de portabilidade ativa; Terraform/AKS/ACR ainda não implantados |

A aplicação congelada `9e3a135` sustenta recuperação, capacidade e os casos de workers.
A fatia HTTP usa derivação própria `045e1ca`, com [runtime identificado](config/http-observability.json).
Não substitui a aplicação nem as evidências das versões anteriores.

## 2. Responsabilidades dos documentos

| Documento | Responsabilidade |
| --- | --- |
| README | Resultado resumido e navegação |
| DESIGN | Contratos, arquitetura e limites dos procedimentos |
| Relatórios em docs | Problema, método executado, resultados, interpretação e fontes |
| Índices de evidências | Pacotes, manifestos, disponibilidade e reprodução offline |
| Guia Kubernetes / Terraform | Preparação, comandos e operação |
| Este plano | Estado da entrega, decisões pendentes e preservação |

## 3. Entregas preservadas e verificação

A consolidação usa registros existentes; não modifica resultados nem reabre ensaios.
O [reprodutor](docs/evidence/observability/reproduce.py) verifica os casos, hashes,
conteúdo dos ZIPs e geração dos diagramas. Os originais selecionados continuam
legíveis no GitHub. A CI confere o pacote offline além das validações existentes;
não inicia o Kind ou a aplicação. Captura diagnóstica não equivale a custo medido.

A tag `v1.2.0-rc.1` identifica a consolidação; os SHAs executados permanecem nos
protocolos. Os dois ZIPs anexados são cópias exatas dos arquivos versionados, com
[checksums](docs/evidence/observability/archives/checksums.sha256). A referência
instrumentada `045e1ca` permanece na branch `codex/v1.3-http-observability` da
aplicação; este fechamento não a remove nem altera imagens históricas.
Não mover tags ou substituir pacotes de releases anteriores.

<a id="3-extensões-possíveis"></a>
<a id="4-exploração-de-observabilidade"></a>
<a id="4-continuidade-condicionada"></a>

## 4. Portabilidade para AKS

**Pergunta inicial:** que adaptações e verificações são necessárias para operar
no AKS uma aplicação já avaliada em Kubernetes local? O resultado mínimo é uma
verificação funcional rastreável, distinguindo contratos preservados, adaptações
a Azure e limites encontrados. Não é comparação de desempenho Kind × AKS, prova
de produção ou execução conjunta dos três mecanismos anteriores.

### Decisões e orçamento

- ACR e AKS na **mesma nova assinatura paga e tenant**, a identificar. Não usar a
  assinatura Student nem depender de trial/crédito para viabilizar esta etapa.
- Antes de qualquer provisionamento, definir um teto operacional aprovado para
  a janela, estimativa por fase, contingência, duração máxima e custo residual.
  Os valores e a autorização ficam em registro privado fora do Git. Esse registro não
  integra evidências públicas nem define parâmetros permanentes da branch.
- O registro de cada janela deve conter `approved_budget`, `currency`,
  `estimated_active_cost`, `estimated_residual_cost`, `contingency_reserve`,
  `max_window_duration`, prazo de retenção e referência da autorização. O executor
  futuro deverá conferir esse registro antes de liberar recursos; esta atualização
  documental não implementa um limitador de cobrança.
- Antes de iniciar ou prolongar uma janela, conferir gasto acumulado, consumo
  ainda não refletido, projeção restante e encerramento. Se a projeção ultrapassar
  o limite autorizado, interromper a exploração e seguir o encerramento seguro.
  Janelas adicionais não renovam automaticamente limites cumulativos acordados.
  Budgets geram alertas, mas não suspendem recursos nem consumo.
- Preferência por **AKS Base / Free tier** e **ACR Basic**, adequados ao recorte de
  laboratório. Free não torna gratuitos nós, discos, rede ou registry, nem oferece
  SLA financeiro. Standard só será considerado diante de necessidade concreta e
  nova estimativa; não é alternativa automática a falta de quota/capacidade.
- Região, versão, VM, número de nós, horas e prazo de retenção continuam abertos.
  O teto não aprova uma configuração desconhecida. `provisioning_authorized`
  permanece falso; as guardas Terraform de aprovação continuam em vigor.

### Etapas e pausas

| Etapa | Trabalho delimitado | Saída e decisão |
| --- | --- | --- |
| Descoberta sem provisionar | Ler assinatura/tenant/oferta, permissões, providers, regiões, quotas e restrições de SKU; conferir AKS e preços | Síntese de viabilidade, topologia candidata, estimativa completa e lacunas; não criar recursos, registrar providers ou atribuir roles |
| Preparação offline | Ajustar Terraform/overlay e conferir planos simulados; preparar imagens/proveniência, verificações funcionais, captura e encerramento | Procedimento executável, duração máxima, destinos novos, acesso e custos revisados; pausa para aprovar o ambiente concreto antes de qualquer recurso cobrado |
| Janela Azure autorizada | Backend/identidades e ACR → AKS → foundations → migrations → runtime → verificações → preservação/encerramento | Uma janela limitada e identificada, interrompida no primeiro impedimento relevante; não exigir interação entre cada recurso do procedimento aprovado |
| Consolidação e reavaliação | Conferir evidências, adaptações, custo observado/pendente e recursos retidos | Decidir entre fechar como complemento de portabilidade ou propor uma única extensão que responda a uma lacuna |

A descoberta deve distinguir catálogo, quota disponível, restrições e capacidade
real de alocação. Nenhum deles isoladamente garante provisionamento. O tamanho do
pool deve satisfazer os requisitos atuais do AKS e os requests, Jobs e componentes
do sistema; não transportar o nó único do Kind como topologia aprovada. O guia
Terraform registra as verificações e fontes. Conta, pagamento e MFA ficam com o
operador; CLI/Terraform concentram a descoberta técnica e a execução rastreável.

A primeira janela só começa com estimativa por fase, prazo de retenção e roteiro
de encerramento prontos. Preparar antes a lógica local evita pagar cluster enquanto
se escreve o instrumento. Não há tentativas ilimitadas, aumento automático de
SKU/replicas, abertura de rede para contornar falha ou busca de resultado favorável.
Falha de acesso, falta de capacidade, custo incompatível ou necessidade de alterar
contrato da aplicação justificam pausa com diagnóstico e alternativas.

### Verificações e evidências pretendidas

O núcleo funcional usa a aplicação congelada `9e3a135`, imagens identificadas por
digest no ACR e dados sintéticos novos. Aceite inclui admissão, conclusão de
Tracking/Order e simulação Notifications por identidade; `202`, ACK ou pod pronto
não bastam. Verificar também pull pela identidade kubelet, privilégios delimitados,
Azure Disk CSI e continuidade dos dados após recriação controlada de pod, além de
tráfego permitido **e bloqueado** pelas NetworkPolicies. Isso não comprova HA ou
restauração de backup. Falha em uma verificação permanece explícita, sem transformar
um deploy bem-sucedido em aceite completo.

A captura deve registrar referências de aplicação/infra/imagens, configuração,
resultados funcionais, inventário e estados antes/depois do encerramento. CLI/JSON
sanitizado é a evidência primária; prints e diagramas têm função explicativa.
Recursos removidos e retidos devem ser identificados separadamente, com custo
residual e prazo. `stop` não equivale a remoção nem a custo total zero. Reativação
só integra o procedimento se houver motivo, tempo e custo previstos.

As avaliações se conectam por intervenção operacional (recuperação), decisão de
capacidade (escala), interpretação dos sinais (observabilidade) e adaptação ao
ambiente gerenciado (portabilidade). Os números do Kind continuam locais. Um
cenário selecionado de recuperação ou tracing pode complementar o aceite Azure,
mas exige objetivo e limite próprios; não repetir as campanhas automaticamente.

### Extensões condicionadas

Primeiro demonstrar funcionamento na Azure. Depois, se houver valor e orçamento,
escolher **uma** lacuna: portar a fatia OTel `045e1ca` com runtime identificado;
ou, em etapa separada, avaliar exportação a Azure Monitor/Application Insights.
Mudar ambiente e destino da telemetria juntos não isola seus efeitos. A integração
AKS/OTLP em preview exige conferir elegibilidade, coleta, retenção e custo; não é
pré-requisito do deploy. Mantém-se a distinção entre informação diagnóstica e custo
da instrumentação, não quantificado na v1.2.

As demais [lacunas e alternativas](docs/OBSERVABILITY_EVALUATION.md#6-interpretação-e-caminhos-de-continuidade)
continuam condicionadas: Prometheus/Grafana para séries e overhead; tracing durável
em AMQP/SQL; segurança de código, dependências, imagens e IaC; service mesh. Segurança
básica de acesso/rede é requisito do ambiente, mas uma avaliação de DevSecOps seria
outro recorte. Não acrescentar ferramentas ou novas perguntas apenas para ampliar
inventário, nem refatorar a aplicação silenciosamente.

Não criar relatório de resultados ou release vazios. Ao encerrar, consolidar o
método efetivamente executado, adaptações, achados e limites no padrão dos três
relatórios existentes, com uma seleção pequena de evidências publicáveis. Custos
técnicos efetivamente incorridos ou estimados podem integrar essa análise,
identificados por período, configuração e situação da cobrança, sem expor o
limite privado de autorização ou dados de faturamento. Se o
ganho for apenas funcional, apresentá-lo como complemento de portabilidade.

## 5. Preservação e histórico

O [histórico até a consolidação de observabilidade](https://github.com/campos-labs/fulfillflow-infra/blob/f6aafa0/RELEASE_PLAN.md)
e o [histórico de capacidade](https://github.com/campos-labs/fulfillflow-infra/blob/58f4483e0fdb2e5273b9b533d9173de494818a3c/RELEASE_PLAN.md)
preservam protocolos, emendas, correções, pausas e decisões. Resultados desfavoráveis,
claims e pastas originais permanecem intactos. IDs de tentativas e nomes históricos
de scripts existem para rastreabilidade; não são etapas pendentes na narrativa.

Os pacotes permitem conferir evidências, não garantem recriação de hardware/runtime,
backup independente ou reprodução externa das medições. Séries não selecionadas e
configurações privadas continuam locais. Scripts operacionais permanecem no Git.

Qualquer execução futura usa destino novo, volume e tempo previamente delimitados,
sem repetir até passar. O [guia](k8s/README.md#diagnóstico-http-com-tracing) preserva
as guardas e a regra de preparação do host. Alterações de contrato, desenho, custo
externo ou risco operacional exigem decisão própria.

Versões seguem capacidades compatíveis em MINOR, correções compatíveis em PATCH,
mudanças incompatíveis em MAJOR e candidatas `-rc.N`. Não reservar uma versão para
cada ferramenta ou ambiente.
