import { Button, EmptyState } from "@footbola/ui";
import { Compass } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useI18n } from "../app/locale";
import { useSession } from "../app/session";

export function NotFoundPage() {
  const navigate = useNavigate();
  const { path } = useSession();
  const { t } = useI18n();
  return (
    <EmptyState
      icon={<Compass />}
      title={t("common", "notFoundTitle")}
      description={t("common", "notFoundBody")}
      action={
        <Button variant="primary" onClick={() => navigate(path("/"))}>
          {t("nav", "dashboard")}
        </Button>
      }
    />
  );
}
