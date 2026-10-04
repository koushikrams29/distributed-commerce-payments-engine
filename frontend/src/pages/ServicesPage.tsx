import { queueUrl, serviceTracesUrl, useToolLinks } from "../app/toolLinks";
import { useResource } from "../app/useResource";
import { HealthBadge } from "../components/StatusBadge";
import { Icon } from "../components/ui/Icon";
import { PageHeader, Panel } from "../components/ui/Panel";
import { EmptyState, Loadable, SkeletonRows } from "../components/ui/States";
import { ToolLink } from "../components/ui/ToolLink";
import { fetchQueues, fetchSystemHealth } from "../lib/api";
import { formatCount, formatRate, formatTime } from "../lib/format";
import { WORK_QUEUES, publishedBy } from "../lib/topology";

export function ServicesPage() {
  const links = useToolLinks();
  const health = useResource(fetchSystemHealth, [], { pollMs: 10_000 });
  const queues = useResource(fetchQueues, [], { pollMs: 10_000 });

  return (
    <div className="page">
      <PageHeader
        title="Services"
        description="Each service's health, its queue, and the events it publishes and consumes."
        actions={
          <>
            <ToolLink className="button button--secondary" href={links.jaegerUrl}>
              Jaeger
            </ToolLink>
            <ToolLink className="button button--secondary" href={links.grafanaUrl}>
              Grafana
            </ToolLink>
            <ToolLink className="button button--secondary" href={links.rabbitmqUrl}>
              RabbitMQ
            </ToolLink>
          </>
        }
      />

      <Panel
        title="Health"
        meta={health.data ? `Checked ${formatTime(health.data.checkedAt)} · every 10 s` : undefined}
        id="health"
        actions={
          <button type="button" className="icon-button" onClick={health.reload} aria-label="Check again" title="Check again">
            <Icon name="refresh" />
          </button>
        }
      >
        <Loadable resource={health} skeleton={<SkeletonRows rows={8} columns={4} />} errorTitle="Couldn't check service health">
          {(data) => (
            <div className="table-scroll">
              <table className="table table--responsive">
                <thead>
                  <tr>
                    <th scope="col">Component</th>
                    <th scope="col">Kind</th>
                    <th scope="col">Status</th>
                    <th scope="col" className="num">
                      Latency
                    </th>
                    <th scope="col">Detail</th>
                    <th scope="col">
                      <span className="visually-hidden">Traces</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.components.map((component) => (
                    <tr key={component.name}>
                      <td data-label="Component" className="mono">
                        <span className={`dot dot--${component.status}`} aria-hidden="true" /> {component.name}
                      </td>
                      <td data-label="Kind" className="muted">
                        {component.kind === "service" ? "Service" : "Infrastructure"}
                      </td>
                      <td data-label="Status">
                        <HealthBadge status={component.status} />
                      </td>
                      <td data-label="Latency" className="num muted">
                        {component.latencyMs === null ? "—" : `${Math.round(component.latencyMs)} ms`}
                      </td>
                      <td data-label="Detail" className={component.status === "up" ? "muted" : "error-text"}>
                        {component.detail ?? (component.kind === "service" ? "Database reachable" : "Reachable")}
                      </td>
                      <td>
                        {component.kind === "service" && (
                          <ToolLink href={serviceTracesUrl(links, component.name)} title={`Recent traces for ${component.name}`}>
                            Traces
                          </ToolLink>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Loadable>
      </Panel>

      <Panel
        title="Queues"
        meta={queues.data ? `Checked ${formatTime(queues.data.checkedAt)}` : undefined}
        id="queues"
      >
        <Loadable resource={queues} skeleton={<SkeletonRows rows={5} columns={6} />} errorTitle="Couldn't read queue depths">
          {(data) =>
            data.queues.length === 0 ? (
              <EmptyState compact title="No work queues found" />
            ) : (
              <div className="table-scroll">
                <table className="table table--responsive">
                  <thead>
                    <tr>
                      <th scope="col">Queue</th>
                      <th scope="col" className="num">
                        Consumers
                      </th>
                      <th scope="col" className="num">
                        Waiting
                      </th>
                      <th scope="col" className="num">
                        In progress
                      </th>
                      <th scope="col" className="num">
                        Retrying
                      </th>
                      <th scope="col" className="num">
                        Dead letters
                      </th>
                      <th scope="col" className="num">
                        In / out
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.queues.map((queue) => (
                      <tr key={queue.name}>
                        <td data-label="Queue">
                          {links.rabbitmqUrl ? (
                            <ToolLink href={queueUrl(links, queue.name)} className="tool-link mono">
                              {queue.name}
                            </ToolLink>
                          ) : (
                            <span className="mono">{queue.name}</span>
                          )}
                        </td>
                        <td data-label="Consumers" className={queue.consumers === 0 ? "num text-danger" : "num"}>
                          {queue.consumers}
                        </td>
                        <td data-label="Waiting" className="num">
                          {formatCount(queue.ready)}
                        </td>
                        <td data-label="In progress" className="num">
                          {formatCount(queue.unacknowledged)}
                        </td>
                        <td data-label="Retrying" className={queue.retrying ? "num text-warning" : "num muted"}>
                          {formatCount(queue.retrying)}
                        </td>
                        <td data-label="Dead letters" className={queue.deadLettered ? "num text-danger" : "num muted"}>
                          {formatCount(queue.deadLettered)}
                        </td>
                        <td data-label="In / out" className="num muted mono">
                          {formatRate(queue.publishRate)} / {formatRate(queue.deliverRate)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )
          }
        </Loadable>
      </Panel>

      <Panel title="Event routing" meta="Topic exchange commerce.events" id="routing">
        <div className="table-scroll">
          <table className="table table--responsive">
            <thead>
              <tr>
                <th scope="col">Service</th>
                <th scope="col">Publishes</th>
                <th scope="col">Consumes (queue)</th>
              </tr>
            </thead>
            <tbody>
              {WORK_QUEUES.map((item) => {
                const publishes = publishedBy(item.service);
                return (
                  <tr key={item.service}>
                    <td data-label="Service" className="mono nowrap">
                      {item.service}
                    </td>
                    <td data-label="Publishes">
                      {publishes.length ? (
                        <span className="chip-list">
                          {publishes.map((type) => (
                            <span key={type} className="chip mono">
                              {type}
                            </span>
                          ))}
                        </span>
                      ) : (
                        <span className="muted">nothing</span>
                      )}
                    </td>
                    <td data-label="Consumes">
                      <div className="mono small muted">{item.queue}</div>
                      <span className="chip-list">
                        {item.routingKeys.map((type) => (
                          <span key={type} className="chip mono">
                            {type}
                          </span>
                        ))}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="panel__note">
            The gateway also binds a private queue to every routing key and relays each event to this
            console. <span className="mono">order.status_changed</span> exists only for the console.
          </p>
        </div>
      </Panel>
    </div>
  );
}