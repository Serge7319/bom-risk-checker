import { Icon, type IconName } from "@/components/Icons";

export function EmptyState({
  icon = "box",
  title,
  body,
  action,
}: {
  icon?: IconName;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="cv-empty" role="status">
      <div className="cv-empty-icon" aria-hidden="true">
        <Icon name={icon} />
      </div>
      <div>
        <h3>{title}</h3>
        <p>{body}</p>
        {action ? <div className="cv-empty-actions">{action}</div> : null}
      </div>
    </div>
  );
}
