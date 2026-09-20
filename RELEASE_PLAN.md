# FulfillFlow Infra — Plano de implantação funcional

## 1. Objetivo, estado e limites

Entregar uma base reproduzível no AKS, com ACR, réplicas fixas e verificação do
fluxo assíncrono da referência definida no [DESIGN.md](DESIGN.md). Parar no aceite
funcional para decidir o escopo posterior. Não há meta de capacidade nem campanha
comparativa autorizada nesta etapa.

| Etapa | Estado |
| --- | --- |
| Base documental | Concluída; responsabilidades preservadas |
| I — Preparação e validação local | Preparação local validada; aceite do ambiente pendente; CI registrada por SHA |
| II — Bootstrap Azure e imagens | Não iniciado |
| III — AKS e implantação | Não iniciado |
| IV — Aceite funcional e pausa | Não iniciado |
| Alternativas A/B | Propostas para revisão; não aprovadas para implementação |

As etapas I–IV compõem o escopo aprovado de preparação. A criação deste repositório
não autoriza gasto, atribuição de permissões, alteração da aplicação ou remoção de
dados. Antes das operações correspondentes, apresentar os recursos/configurações
concretos e confirmar autorização no limite necessário. Não solicitar novamente
autorização para uma operação já aprovada e inalterada.

## 2. Regras de execução deste plano

1. Ler o estado atual e as seções pertinentes do DESIGN antes de cada incremento.
2. Preservar a referência da aplicação e suas evidências. Correções rotineiras de
   documentação, caminhos, diagnóstico e automação pertencentes ao incremento
   podem avançar com testes focais; mudanças de contrato exigem decisão específica.
3. Implementar e revisar por incremento, com testes desde a primeira mudança
   executável. Não interromper a cada arquivo; consolidar dúvidas que realmente
   mudem custo, acesso, persistência, arquitetura ou escopo.
4. Integrar alterações diretamente na `main`, em commits por assunto, após revisão
   do diff e validações pertinentes. Registrar o resultado da CI quando implementada.
   A CI da aplicação permanece no seu repositório.
5. Manter operação utilizável em PowerShell. Conferir executáveis instalados,
   versões, diretório corrente e caminhos com espaços. Não presumir `pwsh`, Azure
   CLI ou Terraform no PATH; não instalar/atualizar ferramentas silenciosamente.
6. Validar configuração e revisar plano antes de apply. Registrar alvo e propriedade
   dos recursos; não usar administração global como atalho para falha de permissão.
   Tratar saída sensível fora do Git e dos logs públicos.
7. Toda operação tem prazo, saída explícita, identificação e diagnóstico preservado.
   Parar na primeira falha operacional; não substituir tentativa inválida nem
   reexecutar uma sequência automaticamente. Reusar estado durável somente quando
   a retomada for segura e documentada.
8. Não repetir suítes aprovadas sem mudança ou dúvida concreta. Ao terminar cada
   incremento, registrar diff, checks, SHA, evidências, limitações e próximo passo.
   Fornecer comando manual apenas quando houver uma operação manual necessária,
   preparada e autorizada, com duração, destino e comportamento de interrupção.
9. Não versionar segredos, planos/state Terraform, kubeconfigs, dumps ou logs brutos.
   Verificar diff e ignorados antes de cada commit. Exemplos usam placeholders;
   códigos/IDs técnicos em inglês e documentação técnica concisa em português.
10. Não criar documentos de contexto redundantes. README orienta o uso; DESIGN
    define arquitetura; este plano registra andamento e decisões de continuidade.

## 3. Incremento I — Preparação e validação local

**Entrega:** estrutura mínima executável, CI de validação e ficha de ambiente,
sem provisionamento Azure.

- Conferir ferramentas e fixar versões compatíveis de Terraform/provider,
  kubectl e helpers realmente necessários. Fixar Azure CLI antes do preflight
  conectado, sem instalá-la como requisito da validação offline. Não depender de versões
  `latest`; registrar locks quando houver implementação.
- Definir assinatura, região, quotas, teto de gasto e período de operação;
  dimensionar nós/discos com margem para sistema, rollout e Jobs. Não transportar
  o orçamento do benchmark histórico como se fosse orçamento do cluster.
- Preparar módulos/configuração Terraform mínimos para bootstrap e ambiente;
  manifests de runtime com dados não sensíveis e configuração de exemplo.
- Resolver acesso do executor ao cluster/ACR/backend, endpoint Kubernetes,
  modelo de secrets e retenção de dados. Consolidar essas decisões antes de apply.
- Implantar CI sem credenciais de cloud para validação de documentos, Terraform
  e manifests presentes. Fixar revisões de actions e permissões mínimas.
- Preparar o verificador funcional com códigos de saída, polling e timeouts
  explícitos. Não adaptar o loadgen síncrono nem criar campanha de carga.

**Verificação:** links e `git diff --check`; Terraform fmt/validate com provider
fixado e sem backend remoto; renderização Kustomize e validação contra schemas
compatíveis; testes focais do verificador e dos scripts, incluindo PowerShell real
quando houver scripts PowerShell. Validação estática não comprova deploy.

**Aceite:** CI do commit aprovada, decisões do ambiente registradas, planos de
bootstrap e configuração revisáveis, sem segredos. Falta de ferramenta ou quota
é pendência explícita, não aprovação substituída por mocks.

### Estado da preparação

Preparados dois roots Terraform (backend e ambiente), locks Windows/Linux,
manifests separados em fundações/migrações/runtime, ficha sem valores de assinatura,
verificador público de conclusão/duplicata e CI de validação sem credenciais cloud.
O exemplo de runtime tem imagem inválida e seletor que impede agendamento.
Não existe workflow de deploy, overlay de ambiente aprovado ou imagem publicada.

Versões e hashes ficam em `config/toolchain.json` e nos locks. Os testes do
verificador usam transporte controlado; Terraform usa provider simulado somente
em planos. Nenhum desses resultados constitui execução funcional no AKS.

Validação local: 48 testes sem skips, incluindo PowerShell real e caminhos com
espaços; Ruff/formatação; 34 objetos renderizados com schemas estritos; Terraform
fmt/validate e 16 planos simulados aprovados. Os testes Terraform de ambiente
selecionam recursos por limitação do mock de `kubelet_identity`; a atribuição
`AcrPull` precisa de conferência real posterior, conforme [infra/README.md](infra/README.md).
A CI registra o resultado por SHA; o aceite ambiental permanece separado.

O aceite permanece dependente de: assinatura/benefício e saldo efetivos, região,
quotas/SKUs, janela e teto de gasto, capacidade alocável, conectividade do executor,
aprovação da proposta de endpoint, canal de secrets e destino protegido de evidências.
A preferência operacional é terminar os preparativos locais antes de consumir
recursos Azure. Valores ausentes em `config/environment.json` não são defaults.
Não iniciar II nem transformar a autorização de preparação em autorização de gasto.

### Perfil provisório de recursos reduzidos — preparação autorizada

Preparar uma implantação funcional econômica sem alterar a aplicação congelada.
O perfil `k8s/overlays/reduced-functional` é separado do exemplo original e mantém
seus bloqueios de agendamento e imagem. Não é um ambiente aprovado para apply.

| Processo | Request CPU candidato | Limit CPU preservado | Memória request/limit |
| --- | --- | --- | --- |
| Cada API/worker (seis) | 150m | 500m | 384 MiB |
| PostgreSQL | 750m | 2000m | 2560 MiB |
| RabbitMQ | 250m | 500m | 512 MiB |
| Cada Job de migration | 250m | 500m | 384 MiB |

Runtime: 1900m/5376 MiB reservados, contra 5500m/5376 MiB no exemplo original.
Executar migrations sequencialmente antes do runtime; a soma conservadora com um
Job adicional seria 2150m/5760 MiB, sem overhead Kubernetes. Não apresentar esses
requests como mínimos essenciais comprovados: são valores iniciais a validar com
jornada sequencial, recuperação e observação de CPU/throttling/memória. A redução
não altera limits, contratos, pools, polling, probes, deadlines, persistência ou
réplicas. Não relaxar verificações para obter aprovação.

**Bloqueio ambiental em 20/09/2026:** o portal mostrou total regional de 6 vCPUs em
Brazil South e East US 2; DSv5 com cota zero nas duas. Em Brazil South, DDSv4 e DSv4
mostraram 4 vCPUs por família e ajuste indisponível no portal. Cotas não comprovam
SKU alocável. Misturar famílias não aumenta o total regional.

A [documentação de pools de sistema](https://learn.microsoft.com/en-us/azure/aks/use-system-pools)
lista dois nós e SKU de pelo menos quatro vCPUs nas restrições, embora a introdução
qualifique parte da orientação como produção. Não assumir exceção de nó único
nem usar apenas a validação permissiva do Terraform como prova de suporte.
Confirmar o contrato aplicável à versão/região antes de selecionar nós. A proposta
anterior de dois nós de quatro vCPUs requer 8 vCPUs, ou 12 com o surge configurado.
Reduzir requests não elimina essa pendência; não desabilitar proteção de upgrade
nem mudar assinatura/benefício automaticamente.

**Antes de apply:** confirmar suporte, quota de família e regional, SKU, capacidade
alocável por nó e requests dos componentes do sistema, espaço para Jobs/rollout,
rede, secrets, persistência e custo real. Crédito preservado para etapa posterior:
US$40; isso não autoriza consumir o restante. Nenhum novo teto/janela de gasto foi
aprovado. A estimativa anterior de dois nós não vale como preço do perfil reduzido.

**Aceite delimitado:** manter todos os cenários funcionais da seção 6 aplicáveis
à topologia aprovada, com origem e limitações. Registrar como pendentes quaisquer
cenários não executáveis; não declarar IV integralmente concluído por aceite
parcial. Reinício de pod não comprova tolerância à perda de nó. Sem avaliação de
capacidade, estabilidade prolongada, HA, autoscaling ou comparação com históricos.
Se a implantação não couber sem mudança estrutural ou enfraquecimento do aceite,
interromper provisionamento e apresentar alternativas de cota/topologia.

**Pausa A/B:** revisar dimensionamento, quotas, requests, limites e instrumentação
antes de decidir o caminho. Ampliar recursos exige nova identidade e verificação
funcional; resultados do perfil provisório não migram automaticamente para uma
campanha posterior. Preparação offline pode prosseguir mesmo com apply bloqueado.

## 4. Incremento II — Bootstrap Azure e imagens

**Pré-condição:** incremento I aceito; alvo, custo e permissões das operações
concretas autorizados.

- Criar backend remoto e recursos de suporte com separação da infraestrutura
  removível. Verificar locking e acesso ao state, sem publicá-lo como artefato.
- Criar grupo de recursos, ACR e identidades/federação necessários. Aplicar
  permissões mínimas; manter login humano separado da identidade de automação.
- Configurar alertas de custo e procedimento de encerramento com recursos ainda
  cobrados identificados. Não tratar alertas como bloqueio automático de gastos.
- Publicar imagens da referência por fluxo auditado do repositório da aplicação;
  preservar Dockerfile e lock. Registrar eventuais mudanças do workflow de
  publicação separadamente do SHA construído, sem mover a tag da aplicação.
- Inventariar os digests de runtime, PostgreSQL e RabbitMQ, origens, plataforma,
  configuração de acesso e retenção. Guardar logs de build/smoke sanitizados.

**Verificação:** autenticação OIDC no escopo definido, escrita/leitura autorizada
do backend, publicação e pull por digest, smoke da imagem e correspondência
source/lock. O sucesso da CI antiga não substitui o smoke da imagem reconstruída.

**Aceite:** backend protegido, imagens identificadas e recursos inventariados.
Convite da equipe permanece adiado para a pausa; não criar contas compartilhadas.

## 5. Incremento III — AKS e implantação

**Pré-condição:** incremento II aceito e plano de criação do cluster autorizado.

- Provisionar AKS, nós fixos, rede, identidades e armazenamento conforme DESIGN.
  Registrar configuração efetiva e custo previsto; não ativar autoscaling.
- Aplicar namespace, políticas, secrets por canal protegido e workloads. Provisionar
  bancos/roles e broker com identidade persistente e credenciais próprias.
- Executar e verificar os três Jobs de migração antes de runtime; preservar
  falhas, não apagar volumes para fazer o startup passar.
- Configurar probes com semântica correta, sinais de shutdown, requests/limits
  e margem dos nós. Healthcheck do worker não vira liveness de dependências.
- Entregar deploy explícito via GitHub Actions, sem rollback automático ou Argo
  CD. Resolver a conectividade do executor sem afrouxar exposição de rede.
- Executar smoke funcional com dados novos e acesso restrito ao Core.

**Verificação:** conexão dos processos somente aos bancos/filas autorizados,
migrations/heads, pods, probes, pull, endpoints internos e jornada assíncrona.
Reaplicar a mesma configuração sem alterações inesperadas; registrar como o
ambiente pode ser reconstruído, sem exigir destruição de dados existentes.

**Aceite:** implantação identificada e reproduzível; jornada concluída no AKS;
pipeline e operação manual coerentes; nenhuma declaração de capacidade ou HA.

## 6. Incremento IV — Aceite funcional e pausa

Executar verificações curtas em recursos de propriedade deste ambiente. Definir
antes de cada cenário IDs, pré-condições, prazo, resultado esperado e restauração
do estado operacional. Reinícios e pausas deliberadas são ações explícitas; não
habilitar injeção contínua de falhas ou carga extensa.

| Cenário | Critério de aceite |
| --- | --- |
| Jornada saudável | Aceite durável, Tracking concluído, estado esperado de Shipment/Order e Notifications `SIMULATED` consultáveis |
| Duplicata | Mesmo ID/bytes não acrescenta efeito ou simulação; resultado original preservado |
| Conflito | Mesmo ID com bytes diferentes é rejeitado sem sobrescrever o original |
| Worker interrompido | Trabalho aceito e pendente retoma após reinício, sem novo webhook e sem duplicação; o registro identifica o ponto observado |
| Notifications pausado | Tracking/Order podem concluir; pendência é visível e a simulação termina após retomada |
| Persistência | Recriação controlada de pod de banco/broker preserva dados e identidade, com retorno funcional verificado |
| Consulta indisponível | Diagnóstico distingue erro de consulta, prazo esgotado, rejeição e pendência; não converte falha em lista vazia/sucesso |

Não alegar falha exatamente após commit/ACK apenas por matar um pod em horário
aproximado. Usar evidência que localize o ponto ou limitar a conclusão à retomada
observada. Testes existentes da aplicação são complementares, não execução no AKS.
Trabalho `BLOCKED` não é recuperação automática: registrar diagnóstico/rearme
autorizado quando pertinente, sem alterar tabelas manualmente.

Preparar um registro curto de aceite com SHAs, digests, heads, topologia efetiva,
parâmetros, cenários, resultados, localização dos originais e limitações. Exportar
e verificar cópia independente das evidências e dados necessários; lacunas de
backup/restauração permanecem explícitas. Atualizar README apenas com comandos
realmente executáveis e estados observados.

**Marco de pausa:** infraestrutura funcional aceita e pacote rastreável entregue.
Parar antes de ativar A/B, iniciar campanha, ampliar recursos ou publicar release.
O aceite funcional pode ser registrado mesmo com limites conhecidos, desde que
nenhum requisito funcional obrigatório tenha falhado ou sido silenciosamente pulado.

Nesse marco, preparar o acesso individual da equipe por convite e roles delimitadas,
para autorização e verificação conjunta. Não associar permissão de colaborador no
GitHub a permissão automática na Azure. Definir se recursos serão mantidos, parados
ou removidos; pausa não autoriza consumo indefinido nem destruição de dados.

## 7. Alternativa A — Implantação e recuperação

**Proposta não aprovada.** Avaliar como verificação funcional e recuperação
automatizada alteram detecção e recuperação de falhas de implantação.

Recorte possível: procedimento básico com acompanhamento do rollout e recuperação
manual definida versus o mesmo deploy acrescido de verificação funcional e
recuperação automatizada. Instrumentação observa as duas condições. Se detecção
e recuperação forem adicionadas juntas, o resultado será sobre o conjunto.

Preparação adicional: versionar imagem/configuração restaurável; definir deadlines,
rollback e confirmação de recuperação; selecionar implantação saudável e falhas
delimitadas, como imagem indisponível e falha funcional demonstrável no piloto.
Manter schemas compatíveis: rollback de Deployment não restaura banco, secrets
externos ou todo o ambiente. Identificar a revisão efetivamente exercitada para
que réplicas antigas não escondam defeitos da nova.

Resultados possíveis: detecção, recuperação funcional, conclusões dentro do prazo,
duração, intervenções e falsos alarmes. Definir início/fim de cada tempo e separar
reação humana de execução técnica. Falha bloqueada sem indisponibilidade também
é resultado. Falhas induzidas não estimam diretamente MTBF de produção.

Manter réplicas fixas. GitOps/Argo CD não é pré-requisito; se aprovado depois,
reversão deve atualizar o estado desejado e não disputar com reconciliação.

## 8. Alternativa B — Autoescalonamento e processamento

**Proposta não aprovada.** Avaliar como uma política de autoescalonamento afeta
conclusão de trabalho, backlog e recuperação diante de variações controladas de
entrada, mantendo estável o procedimento de implantação.

Recorte possível: réplicas fixas versus uma política escolhida, aplicada a um
workload delimitado. Não comparar simultaneamente HPA, KEDA, todos os workers e
estratégias de deploy. Fixar capacidade dos nós inicialmente para distinguir
escala de pods de escala do cluster.

Preparação adicional: carga assíncrona que distinga oferecido/aceito/concluído,
backlog por etapa, idade da pendência e drain; métrica de escala compatível com
ACK antecipado e trabalho durável local; pools SQL, limites de réplicas e recursos
totais. Fila RabbitMQ vazia não é critério suficiente para reduzir a zero.
Manter ao menos um processador por serviço até existir recuperação demonstrada
para trabalho já retirado do broker.

Resultados possíveis: conclusão por segundo, latência de conclusão, idade/backlog,
tempo de recuperação, erros e consumo/custo. HTTP 202 rápido não comprova aumento
de capacidade; manter usuários virtuais iguais também não fixa a carga oferecida.
Polling e instrumentação entram na identidade do protocolo. Não exigir benefício
positivo para aceitar os resultados nem ajustar margem após observá-los.

## 9. Decisão e retomada

Na pausa, a equipe revisa custo, prazo, observabilidade disponível e riscos
demonstrados na preparação. Pode escolher A, B, outro recorte delimitado ou encerrar
no aceite funcional. Não selecionar a alternativa apenas por um piloto favorável.

Registrar aqui a decisão, justificativa, escopo excluído, requisitos adicionais,
limite de esforço e critérios de interrupção. Atualizar o DESIGN somente para
contratos aprovados e decompor o trabalho escolhido em incrementos executáveis.
Antes de coleta comparativa, fixar cenários, identidades, ordem, repetições, métricas,
agregação e tratamento de falhas/timeouts. Pilotos e tentativas inválidas ficam
preservados e separados; não há número de repetições ou significância garantidos
neste plano inicial.

| Decisão | Estado |
| --- | --- |
| Ambiente comum AKS + ACR, réplicas fixas | Aprovado como alvo; execução pendente |
| Assinatura, região, orçamento, SKUs e conectividade | A definir no incremento I |
| Segredos, retenção e acesso do executor | A definir antes do deploy |
| Convite/acessos da equipe | Adiados para o marco de pausa |
| Alternativa posterior | Não selecionada |
| Campanha comparativa | Não autorizada |
| Tag/release de infraestrutura | Não autorizada nesta preparação |
