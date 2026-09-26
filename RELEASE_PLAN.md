# FulfillFlow Infra — Plano de entrega

## 1. Estado atual

**v1.0.0 — avaliação operacional concluída em Kind; pausa para decisão de continuidade.**
A aplicação v1.3.0-rc.1 permanece congelada. O último encerramento conferiu a configuração
saudável, pausou os workloads e parou o nó, preservando dados e evidências.
Não há implantação AKS, publicação ACR ou autoescalonamento neste aceite.

Resultados e protocolos pertencem à [avaliação operacional](docs/OPERATIONAL_EVALUATION.md).
O [DESIGN](DESIGN.md) define os contratos; o [guia Kubernetes](k8s/README.md)
contém os comandos. Este plano registra entregas e decisões futuras, sem repetir
as tabelas ou o diário das execuções.

| Entrega concluída | Alcance |
| --- | --- |
| Ambiente e operação | Kind isolado, aplicação congelada, persistência, verificação e restauração delimitada de um workload |
| Avaliação | Comparação de 20 tentativas; protocolo separado com seis pendências e três inconclusões. Pilotos e séries interrompidas excluídos |
| Documentação e evidências | Relatório, registros selecionados e dois pacotes completos versionados, com origem e hashes |

Os SHAs executados, CIs e arquivos correspondentes constam no relatório. O
[registro anterior à consolidação](https://github.com/campos-labs/fulfillflow-infra/blob/47dbd111ad4eff89a8e64c7b50d7d2c59c23baf7/RELEASE_PLAN.md)
preserva o histórico detalhado. Comandos e propostas daquele registro não são
instruções vigentes de execução.

## 2. Pendências de encerramento

| Item | Tratamento |
| --- | --- |
| Evidências | Dois conjuntos concluídos disponíveis no Git como seleção e ZIPs originais revisados para compartilhamento. Pilotos e séries interrompidas preservados localmente, com síntese de exclusões |
| Backup e recuperação | Dois ZIPs versionados com hashes para conferência do download. Isso não comprova restauração de bancos, volumes ou ambiente após perda do equipamento |
| Referência de infraestrutura | [v1.0.0](https://github.com/campos-labs/fulfillflow-infra/releases/tag/v1.0.0) identifica o fechamento documental e operacional; SHAs das execuções permanecem no relatório e nos protocolos |
| NetworkPolicies | Seletores validados; tráfego permitido/bloqueado não ensaiado. Não declarar isolamento efetivo a partir da CI |
| Capacidade, estabilidade prolongada e HA | Não avaliadas; fora do aceite funcional e da comparação operacional |

Não repetir uma série concluída para completar outra, ampliar denominadores ou
substituir registros interrompidos. Correções documentais não alteram os critérios
ou SHAs das execuções. Uma nova execução exige protocolo e destino próprios.

## 3. Extensões possíveis

Nenhuma extensão é condição para concluir a avaliação atual. A escolha deve resolver
uma lacuna definida, com referência congelada, custo, critérios e resultados esperados
no sentido de verificáveis, não de necessariamente favoráveis. Não abrir uma
branch por condição comparada nem implementar todas as alternativas abaixo.

### AKS e ACR — verificação de implantação

Objetivo possível: verificar se a referência e os procedimentos funcionais operam
no AKS e identificar adaptações de identidade, armazenamento, rede e encerramento.
ACR pertence a essa implantação; não é requisito retroativo dos resultados Kind.

A preparação Azure e as consultas anteriores não estabeleceram uma configuração
provisionável. Antes de qualquer apply, reconferir assinatura, região, quotas,
restrições de SKU, capacidade do pool, acessos, orçamento e custos residuais.
Validar o plano efetivo e as guardas do [guia Terraform](infra/README.md).
Não tratar uma quota positiva ou uma renderização aprovada como garantia de alocação.

Uma verificação complementar pode manter réplicas fixas e exercitar jornada,
restauração e observação dos eventos identificados. Seus resultados pertencem a
um conjunto separado. Para comparar tempos no AKS, executar ambas as condições
ali, sob protocolo previamente definido; não comparar controle local com automação
na nuvem nem converter medições Kind em evidência de desempenho Azure.

### Autoescalonamento e trabalho concluído

Objetivo possível: avaliar uma política de réplicas diante de entrada variável,
comparando réplicas fixas e escala de um workload. Manter capacidade dos nós e
procedimento de implantação controlados inicialmente.

Requer carga que distinga oferecido, aceito e concluído; idade/backlog por etapa,
drain, recursos totais e prazos. ACK pode anteceder o processamento local: fila
RabbitMQ vazia não basta para reduzir workers a zero. Preservar pelo menos um
processador até haver recuperação demonstrada das pendências locais. HPA ou KEDA
são opções a avaliar após escolher uma métrica adequada, sem adoção conjunta automática.
Não presumir que admissão HTTP mais rápida represente maior capacidade de conclusão.

### Outras capacidades — somente com finalidade definida

| Capacidade | Quando pode acrescentar informação | Delimitação |
| --- | --- | --- |
| OpenTelemetry e métricas de pendência | Diagnosticar em qual etapa o trabalho aguarda e correlacionar tentativas | Instrumentação nova altera a identidade da avaliação; tracing completo não está comprovado pelo aceite atual |
| Argo CD / GitOps | Avaliar reconciliação de configuração e tratamento de drift | Exige separar o controlador do executor de restauração para evitar concorrência de mutações; não é necessário para a comparação concluída |
| SAST | Acrescentar uma verificação de segurança à entrega | Definir achados e política de tratamento; não demonstra recuperação ou desempenho operacional |
| Locust ou k6 | Gerar entrada controlada para um objetivo de capacidade | Escolher um gerador e adaptar a observação assíncrona; não reutilizar carga síncrona tratando 202 como conclusão |

Terraform e GitHub Actions já integram a preparação e validação deste repositório.
Não equivalem a provisionamento Azure ou pipeline de deploy remoto executados.
Uma extensão escolhida deverá ter plano próprio, testes desde o primeiro incremento
e pausa ao atingir seu aceite. Nova versão/branch será decidida nesse momento;
nenhuma numeração futura ou implementação está comprometida agora.

## 4. Versionamento e continuidade

As versões da infraestrutura são independentes das versões da aplicação. A v1.0.0
fixa as interfaces operacionais documentadas: comandos, configuração e formatos de
saída suportados. Correções compatíveis incrementam PATCH; novas capacidades
compatíveis, MINOR; mudanças incompatíveis, MAJOR. Candidatas usam `-rc.N`.
AKS e autoescalonamento não têm numeração reservada: ela dependerá da mudança real.
Referências publicadas e registros de execução não são substituídos retrospectivamente.


1. Ler os contratos pertinentes do DESIGN e o estado deste plano. Preservar a
   aplicação e as evidências congeladas; não alterar runtime para acomodar um resultado.
2. Resolver ajustes rotineiros no incremento autorizado. Mudanças de contrato,
   ambiente, custo, acesso ou persistência exigem decisão específica e plano concreto.
3. Integrar diretamente na `main`, por assunto, depois de revisão e validações
   pertinentes. A CI da aplicação permanece no repositório de origem.
4. Manter comandos utilizáveis em PowerShell. Conferir executáveis e versões;
   não alterar ferramentas do operador ou PATH silenciosamente.
5. Validar configuração antes de mutação, com contexto, identidade e propriedade
   dos recursos explícitos. Falha de permissão não autoriza administração global.
6. Toda operação tem prazo, diagnóstico e encerramento. Parar na primeira falha
   inesperada; não repetir implantação, webhook ou patch com resultado incerto.
   Retomada usa reconciliação e guardas documentadas, sem apagar registros anteriores.
7. Cobrir comportamento alterado com verificações pertinentes. Não repetir suítes
   aprovadas sem mudança ou dúvida concreta; documentação sem runtime exige revisão
   de links, exemplos, dados, fronteiras e diff.
8. Não versionar secrets, kubeconfigs, planos/state Terraform, dumps ou caminhos
   pessoais. Saídas operacionais só entram em pacotes delimitados, revisados para
   compartilhamento e com hashes. Exemplos usam placeholders; dados derivados
   identificam fonte e transformação, sem reescrever evidências originais.
9. Reportar alterações, checks, SHA e limitações. Fornecer comando manual somente
   para operação preparada, necessária e autorizada. Atualizar o documento responsável
   pelo assunto, evitando cópias de resultados e documentos de contexto redundantes.
