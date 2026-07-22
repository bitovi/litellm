-- AlterTable
ALTER TABLE "LiteLLM_TeamMembership" ADD COLUMN IF NOT EXISTS "metadata" JSONB NOT NULL DEFAULT '{}';
