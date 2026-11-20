
from django.core.management.base import BaseCommand, CommandError

from research_library.models import ResearchResource
from research_library.ingestion import ingest_research_resource


class Command(BaseCommand):
    help = "Ingest a research PDF into MinIO."

    def add_arguments(self, parser):
        parser.add_argument(
            "--resource-id",
            type=int,
            required=True,
            help="ID of the ResearchResource to ingest.",
        )

    def handle(self, *args, **options):
        resource_id = options["resource_id"]

        try:
            resource = ResearchResource.objects.get(id=resource_id)
        except ResearchResource.DoesNotExist:
            raise CommandError(
                f"Research resource with ID {resource_id} does not exist."
            )

        try:
            ingestion = ingest_research_resource(resource)
        except Exception as exc:
            raise CommandError(f"Ingestion failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Ingestion status: {ingestion.status}\n"
                f"Resource ID: {resource.id}\n"
                f"Bucket: {ingestion.bucket_name}\n"
                f"Object key: {ingestion.object_key}\n"
                f"SHA-256: {ingestion.checksum_sha256}\n"
                f"File size: {ingestion.file_size} bytes"
            )
        )
