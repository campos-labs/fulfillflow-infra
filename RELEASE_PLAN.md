# FulfillFlow Infra — Plano de implantação funcional

## 1. Objetivo, estado e limites

**Estado atual: aceite funcional local em Kind concluído; pausa de reavaliação.**
Os estados II–IV abaixo referem-se exclusivamente ao alvo Azure ainda pendente.

Entregar uma base reproduzível no AKS, com ACR, réplicas fixas e verificação do
fluxo assíncrono da referência definida no [DESIGN.md](DESIGN.md). Parar no aceite
funcional para decidir o escopo posterior. Não há meta de capacidade nem campanha
comparativa autorizada nesta etapa.

| Etapa | Estado |
| --- | --- |
| Base documental | Concluída; responsabilidades preservadas |
| I — Preparação e validação | Código e CI aprovados; seleção e aceite do ambiente Azure pendentes |
| L1–L4 — Caminho Kind | Aceite funcional local concluído; ambiente preservado e parado |
| II — Bootstrap Azure e imagens | Não iniciado |
| III — AKS e implantação | Não iniciado |
| IV — Aceite funcional e pausa | Não iniciado |
| Alternativas A/B | Propostas para revisão; não aprovadas para implementação |

O caminho local está encerrado no marco L4. Os incrementos Azure permanecem
planejados, sem retomada automática. Mudanças de custo, acesso, aplicação ou
retenção exigem escopo concreto autorizado; preservar autorizações já concedidas
e não solicitar novamente aprovação para operações inalteradas.

### Caminho local — aceite em 21/09/2026

O caminho Kind permite a pausa com aceite funcional local, sem exigir implantação
prévia no AKS. Não encerra os incrementos II–IV de nuvem. A seleção ambiental Azure
e seu bloqueio estão registrados na seção 3.

Etapas executadas:

1. **L1 — Cluster isolado:** Kind portátil e imagem de nó fixados, checksum
   conferido, kubeconfig próprio e API em loopback; recursos alheios preservados.
2. **L2 — Implantação local:** imagem do SHA congelado reconstruída sem alterar
   aplicação/lock; credenciais exclusivas, PVCs novos e migrations sequenciais
   antes das três APIs e três workers.
3. **L3 — Aceite local:** cenários da seção 6 com dados sintéticos novos, prazos
   finitos e evidências por cenário; nenhuma campanha ou comparação com AKS.
4. **L4 — Pausa:** identidade, resultados e limites consolidados; evidências e
   dumps exportados; workloads e nó parados, com dados preservados.

O perfil e suas diferenças em relação ao AKS são definidos no DESIGN, seções 7 e
10; ferramentas em `config/kind-toolchain.json`. A execução usou Docker/WSL com
cgroup v1 e Kubernetes 1.34.0, em janela delimitada. Não é recomendação de versão
para a nuvem nem ensaio de capacidade do notebook.

**Estado observado: L1–L3 concluídos; L4 atingido, evolução pausada.**
Kind iniciou, oito componentes ficaram prontos e os três heads foram verificados:
`1301_core`, `1203_tracking`, `1301_notifications`. Imagem reconstruída do SHA
congelado, sem alteração de código/lock; identidade no pacote de evidências.

| Cenário local | Resultado e limite |
| --- | --- |
| Jornada + duplicata | 202 → Tracking concluído → Order FULFILLED → Notification SIMULATED; uma duplicata preservou identidades e efeito único |
| Core worker parado | Evento admitido permaneceu pendente e concluiu após retomada, sem novo webhook; parada anterior à admissão, não exatamente após ACK |
| Mesmo ID, outro conteúdo assinado | 409 e registro original preservado; efeitos continuaram únicos |
| Notifications pausado | Tracking/Order concluíram com simulação pendente; retomada concluiu sem novo webhook |
| Broker recriado com trabalho pendente | Novo UID, mesmo PVC, conclusão posterior única; cenário combinado, sem atribuição causal isolada ao broker |
| API Notifications parada | Consulta retornou 503, sem lista vazia; observação retomada preservou o evento |
| PostgreSQL recriado | Novo UID, mesmos PVCs, identidades/resultados/efeitos preservados; não representa falha do host |

Verificações: 54 testes Python, Ruff/formatação, nove renderizações com schemas e
16 testes Terraform com provider simulado aprovados. Admissão e execução reais
ocorreram no API server local 1.34.0; schemas estáticos permanecem 1.35.0.
A [CI Linux/Windows](https://github.com/campos-labs/fulfillflow-infra/actions/runs/35564908760)
foi aprovada no SHA de infraestrutura `d98adda9a27a3b6d0adb1b55e5cc51c674ce20d9`.
Ela executa validações estáticas, unitárias e planos simulados; os cenários no
cluster foram executados localmente, fora da CI.

Pacote local não versionado: `artifacts/kind-functional-01/summary.json`,
`acceptance-results.json`, observações JSONL, manifests efetivos, heads, imagens e
`checksums.json` (23 arquivos). O fechamento está em
`artifacts/kind-functional-01-closure.json`. `acceptance_local.py` registra o
procedimento adicional de recuperação; contém caminhos locais e não é um runner
portátil ou etapa da CI. Cópia adicional foi conferida no mesmo computador. Dumps dos três bancos foram exportados em
diretório protegido fora do Git; restauração independente não foi exercitada.
Não chamar cópia no mesmo host de proteção contra perda do equipamento.

NetworkPolicies têm suporte no Kind fixado, mas os cenários de permissão/bloqueio
de tráfego não foram ensaiados. Essa lacuna permanece distinta das verificações
Azure e não invalida os resultados funcionais delimitados acima.

Na pausa, os seis Deployments e os dois StatefulSets foram escalados a zero e o
container `fulfillflow-local-01-control-plane` foi parado. PVCs, imagens, recursos
históricos e credenciais foram preservados. A retomada do mesmo ambiente segue
[k8s/README.md](k8s/README.md#instalação-e-operação-local); não é nova instalação.

**Decisão seguinte pendente:** ambiente da avaliação (local ou janela AKS), caminho
A/B, orçamento/esforço e critérios. Sem campanha, trial, conversão de assinatura,
provisionamento Azure, tag ou release de infraestrutura neste marco.

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
O overlay Kind tem aceite local; não existe workflow de deploy Azure, overlay
AKS aprovado ou imagem publicada no ACR.

Versões e hashes ficam em `config/toolchain.json` e nos locks. Os testes do
verificador usam transporte controlado; Terraform usa provider simulado somente
em planos. Nenhum desses resultados constitui execução funcional no AKS.

Os resultados atuais e a CI estão na seção 1. Os testes Terraform de ambiente
selecionam recursos por limitação do mock de `kubelet_identity`; a atribuição
`AcrPull` exige conferência real posterior, conforme [infra/README.md](infra/README.md).

O aceite ambiental Azure depende de assinatura/benefício e saldo efetivos, região,
quotas/SKUs, janela e teto de gasto, capacidade alocável, conectividade do executor,
endpoint, canal de secrets e destino protegido de evidências. Os campos Azure
ausentes em `config/environment.json` não são defaults nem registro das consultas
históricas. A preparação não autoriza provisionamento durante a pausa.

### Recursos e seleção ambiental Azure

`k8s/overlays/reduced-functional` mantém os bloqueios de agendamento e imagem do
exemplo AKS. Seus requests são os definidos no DESIGN, seção 7, também usados no
Kind: 1900m/5376 MiB de runtime e 250m/384 MiB por Job. Não são mínimos medidos;
o aceite sequencial local não demonstra capacidade, ausência de throttling ou
comportamento sob carga. Ampliar recursos exige nova identidade e verificação.

**Consultas encerradas em 20/09/2026:** cotas positivas não identificaram, por si
só, um candidato alocável. As validações encontraram restrição de regiões e recusa
explícita de `Standard_D4s_v3` pelo AKS em Canada Central. As regiões permitidas
consultadas foram Brazil South, Canada Central, North Central US, Mexico Central
e Spain Central. A tentativa de pedido de cota pelo portal não gerou protocolo;
falha de interface não é aprovação nem recusa de suporte. Nenhum recurso cobrado
do projeto foi criado nessas tentativas.

As instruções superadas de busca e suporte permanecem no histórico Git. Novas
buscas, provisionamentos, conversão de assinatura e trials ficam suspensos até
a decisão da seção 9. A reserva de US$40 para etapa posterior permanece como
restrição de planejamento, não autorização para consumir o restante do saldo.
Créditos, quotas, disponibilidade e preços devem ser reconferidos na retomada.

Antes de apply Azure, confirmar suporte ao pool/versão, quotas regional e de
família, SKU, capacidade alocável, componentes de sistema, Jobs, rede, secrets,
armazenamento e custo. Menor request de pods não reduz a cota de vCPUs dos nós.
Não adotar nó único ou reduzir proteções de manutenção para contornar um bloqueio.

### Manutenção da proposta AKS

A proposta mantém nós fixos, autoscaling desabilitado,
`node_os_upgrade_channel = "None"` e `max_surge = "1"`. A janela funcional não
inclui upgrades ou rotação planejados; isso não impede reparos do serviço nem
constitui política permanente de atualização. Incluir o nó temporário nas cotas
e no custo antes de autorizar manutenção.

Revisar qualquer atualização, substituição ou uso de `temporary_name_for_rotation`
no plano Terraform. Falta de capacidade exige reavaliação, sem troca automática
de SKU ou retry. Surge de nós é distinto de `maxSurge` dos Deployments. Os detalhes
da configuração e encerramento pertencem a [infra/README.md](infra/README.md).

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

Estes critérios servem ao aceite local L3 e, em execução própria, ao IV no AKS.
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

**Marco de pausa:** aceite funcional local (L4) ou aceite no AKS, sempre identificado
como tal, e pacote rastreável entregue. L4 pode ocorrer antes dos incrementos Azure.
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

Na pausa atual, decidir primeiro o ambiente: continuar em Kubernetes local,
usar Kind como preparação e validar no AKS em janela curta com assinatura viável,
ou encerrar no aceite funcional. Uma troca para VM/K3s ou outro provedor requer
decisão própria. Local não comprova integrações Azure e não deve gerar uma segunda
campanha apenas para compensar sua indisponibilidade.

Se houver continuidade, escolher separadamente A, B ou outro recorte delimitado,
considerando custo, prazo, observabilidade e riscos observados. Não selecionar a
alternativa apenas por um piloto favorável.

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
| Ambiente Kind | Aceite funcional concluído; nó parado e dados preservados |
| Ambiente da continuidade | Local, janela AKS ou encerramento: decisão pendente |
| Assinatura, região, orçamento, SKUs e conectividade Azure | Seleção executável pendente; consultas históricas não autorizam apply |
| Segredos, retenção e acesso do executor | Configurados localmente; solução Azure pendente |
| Cópia independente e restauração | Não verificadas; cópia no mesmo host e dumps preservados |
| Convite/acessos da equipe | Adiados para o marco de pausa |
| Alternativa posterior | Não selecionada |
| Campanha comparativa | Não autorizada |
| Tag/release de infraestrutura | Não autorizada nesta preparação |
