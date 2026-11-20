
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from minio.error import S3Error
from pypdf import PdfWriter

from .models import ResearchIngestion

from .models import (
    ResearchResource,
    SavedResearchItem,
    ResearchCollection,
    CollectionItem,
)

User = get_user_model()


class ResearchLibraryTests(TestCase):

    @classmethod
    def setUpTestData(cls):

        cls.member_a = User.objects.create_user(
            username="library_student_a",
            email="library_a@example.com",
            password="TestPass123!"
        )

        cls.member_b = User.objects.create_user(
            username="library_student_b",
            email="library_b@example.com",
            password="TestPass123!"
        )

        cls.resource = ResearchResource.objects.create(
            title="Machine Learning Fundamentals",
            description="Introduction to machine learning.",
            resource_type="link",
            url="https://example.org/ml",
            uploaded_by=cls.member_a
        )

        cls.saved_item = SavedResearchItem.objects.create(
            user=cls.member_a,
            resource=cls.resource,
            private_notes="My original private note."
        )

    # =====================================
    # TEST 1: VIEW RESEARCH LIBRARY
    # =====================================

    def test_member_can_view_research_library(self):

        self.client.force_login(self.member_a)

        response = self.client.get(
            reverse("research_library:library_home")
        )

        self.assertEqual(response.status_code, 200)

        self.assertTemplateUsed(
            response,
            "research_library/library_home.html"
        )

    # =====================================
    # TEST 2: SAVE RESOURCE USING URL
    # =====================================

    def test_member_can_save_resource_using_url(self):

        self.client.force_login(self.member_b)

        response = self.client.post(
            reverse("research_library:save"),
            {
                "source_type": "url",
                "identifier": "https://example.org/new-paper",
                "title": "New Research Paper",
                "private_notes": "Review this paper."
            }
        )

        self.assertEqual(response.status_code, 302)

        resource = ResearchResource.objects.get(
            url="https://example.org/new-paper"
        )

        saved_item = SavedResearchItem.objects.get(
            user=self.member_b,
            resource=resource
        )

        self.assertEqual(
            saved_item.private_notes,
            "Review this paper."
        )

    # =====================================
    # TEST 3: PREVENT DUPLICATE URL SAVES
    # =====================================

    def test_duplicate_url_does_not_create_duplicate_record(self):

        self.client.force_login(self.member_a)

        response = self.client.post(
            reverse("research_library:save"),
            {
                "source_type": "url",
                "identifier": "https://example.org/ml",
                "title": "Machine Learning Fundamentals",
                "private_notes": ""
            }
        )

        self.assertEqual(response.status_code, 302)

        self.assertEqual(
            ResearchResource.objects.filter(
                url="https://example.org/ml"
            ).count(),
            1
        )

        self.assertEqual(
            SavedResearchItem.objects.filter(
                user=self.member_a,
                resource=self.resource
            ).count(),
            1
        )

    # =====================================
    # TEST 4: SAVE RESOURCE USING DOI
    # =====================================

    @patch(
        "research_library.services.fetch_crossref_metadata"
    )
    def test_member_can_save_resource_using_doi(
        self,
        mock_crossref
    ):

        mock_crossref.return_value = {
            "title": "Advanced Machine Learning",
            "description": "Research publication abstract.",
            "url": "https://doi.org/10.1234/test"
        }

        self.client.force_login(self.member_a)

        response = self.client.post(
            reverse("research_library:save"),
            {
                "source_type": "doi",
                "identifier": "10.1234/test",
                "title": "",
                "private_notes": "Read the methodology."
            }
        )

        self.assertEqual(response.status_code, 302)

        resource = ResearchResource.objects.get(
            doi="10.1234/test"
        )

        self.assertEqual(
            resource.title,
            "Advanced Machine Learning"
        )

        self.assertTrue(
            SavedResearchItem.objects.filter(
                user=self.member_a,
                resource=resource
            ).exists()
        )

    # =====================================
    # TEST 5: SAVE RESOURCE USING ARXIV ID
    # =====================================

    @patch(
        "research_library.services.fetch_arxiv_metadata"
    )
    def test_member_can_save_resource_using_arxiv(
        self,
        mock_arxiv
    ):

        mock_arxiv.return_value = {
            "title": "Research on Neural Networks",
            "description": "Neural network research abstract.",
            "url": "https://arxiv.org/abs/2501.12345"
        }

        self.client.force_login(self.member_b)

        response = self.client.post(
            reverse("research_library:save"),
            {
                "source_type": "arxiv",
                "identifier": "2501.12345",
                "title": "",
                "private_notes": "Study this paper."
            }
        )

        self.assertEqual(response.status_code, 302)

        resource = ResearchResource.objects.get(
            arxiv_id="2501.12345"
        )

        self.assertEqual(
            resource.title,
            "Research on Neural Networks"
        )

        self.assertTrue(
            SavedResearchItem.objects.filter(
                user=self.member_b,
                resource=resource
            ).exists()
        )

    # =====================================
    # TEST 6: MULTIPLE MEMBERS SHARE RESOURCE
    # =====================================

    def test_two_members_can_save_same_resource(self):

        SavedResearchItem.objects.create(
            user=self.member_b,
            resource=self.resource
        )

        self.assertEqual(
            SavedResearchItem.objects.filter(
                resource=self.resource
            ).count(),
            2
        )

        self.assertEqual(
            ResearchResource.objects.filter(
                url="https://example.org/ml"
            ).count(),
            1
        )

    # =====================================
    # TEST 7: CREATE PERSONAL COLLECTION
    # =====================================

    def test_member_can_create_collection(self):

        self.client.force_login(self.member_a)

        response = self.client.post(
            reverse("research_library:create_collection"),
            {
                "name": "Machine Learning Papers",
                "description": "My ML research collection."
            }
        )

        self.assertEqual(response.status_code, 302)

        collection = ResearchCollection.objects.get(
            owner=self.member_a,
            name="Machine Learning Papers"
        )

        self.assertEqual(
            collection.description,
            "My ML research collection."
        )

    # =====================================
    # TEST 8: ADD SAVED ITEM TO COLLECTION
    # =====================================

    def test_member_can_add_item_to_collection(self):

        collection = ResearchCollection.objects.create(
            owner=self.member_a,
            name="My Research"
        )

        self.client.force_login(self.member_a)

        response = self.client.post(
            reverse("research_library:add_to_collection"),
            {
                "collection": collection.id,
                "saved_item": self.saved_item.id
            }
        )

        self.assertEqual(response.status_code, 302)

        self.assertTrue(
            CollectionItem.objects.filter(
                collection=collection,
                saved_item=self.saved_item
            ).exists()
        )

    # =====================================
    # TEST 9: PREVENT CROSS-MEMBER COLLECTION ACCESS
    # =====================================

    def test_member_cannot_add_another_members_saved_item(self):

        collection = ResearchCollection.objects.create(
            owner=self.member_a,
            name="Private Collection"
        )

        other_resource = ResearchResource.objects.create(
            title="Other Member Research",
            resource_type="link",
            url="https://example.org/other",
            uploaded_by=self.member_b
        )

        other_saved_item = SavedResearchItem.objects.create(
            user=self.member_b,
            resource=other_resource
        )

        self.client.force_login(self.member_a)

        response = self.client.post(
            reverse("research_library:add_to_collection"),
            {
                "collection": collection.id,
                "saved_item": other_saved_item.id
            }
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            CollectionItem.objects.filter(
                collection=collection,
                saved_item=other_saved_item
            ).exists()
        )

    # =====================================
    # TEST 10: REMOVE ITEM FROM COLLECTION
    # =====================================

    def test_member_can_remove_item_from_collection(self):

        collection = ResearchCollection.objects.create(
            owner=self.member_a,
            name="Test Collection"
        )

        collection_item = CollectionItem.objects.create(
            collection=collection,
            saved_item=self.saved_item
        )

        self.client.force_login(self.member_a)

        response = self.client.post(
            reverse(
                "research_library:remove_from_collection",
                args=[collection_item.id]
            )
        )

        self.assertEqual(response.status_code, 302)

        self.assertFalse(
            CollectionItem.objects.filter(
                id=collection_item.id
            ).exists()
        )

        # The personal saved item must remain
        self.assertTrue(
            SavedResearchItem.objects.filter(
                id=self.saved_item.id
            ).exists()
        )

    # =====================================
    # TEST 11: UPDATE PRIVATE NOTES
    # =====================================

    def test_member_can_update_private_notes(self):

        self.client.force_login(self.member_a)

        response = self.client.post(
            reverse(
                "research_library:update_note",
                args=[self.saved_item.id]
            ),
            {
                "private_notes": "Updated private research notes."
            }
        )

        self.assertEqual(response.status_code, 302)

        self.saved_item.refresh_from_db()

        self.assertEqual(
            self.saved_item.private_notes,
            "Updated private research notes."
        )

    # =====================================
    # TEST 12: PRIVATE NOTES ARE PROTECTED
    # =====================================

    def test_other_member_cannot_update_private_notes(self):

        self.client.force_login(self.member_b)

        response = self.client.post(
            reverse(
                "research_library:update_note",
                args=[self.saved_item.id]
            ),
            {
                "private_notes": "Unauthorized note change."
            }
        )

        self.assertEqual(response.status_code, 404)

        self.saved_item.refresh_from_db()

        self.assertEqual(
            self.saved_item.private_notes,
            "My original private note."
        )

    # =====================================
    # TEST 13: UNIVERSITY-WIDE SAVE COUNT
    # =====================================

    def test_library_displays_distinct_member_save_count(self):

        SavedResearchItem.objects.create(
            user=self.member_b,
            resource=self.resource
        )

        self.client.force_login(self.member_a)

        response = self.client.get(
            reverse("research_library:library_home")
        )

        self.assertEqual(response.status_code, 200)

        resource_in_context = next(
            resource
            for resource in response.context["library_resources"]
            if resource.id == self.resource.id
        )

        self.assertEqual(
            resource_in_context.member_save_count,
            2
        )

    # =====================================
    # TEST 14: SEARCH RESEARCH SOURCES
    # =====================================

    @patch(
        "research_library.views.search_research_sources"
    )
    def test_member_can_search_research_sources(
        self,
        mock_search
    ):

        mock_search.return_value = (
            [
                {
                    "provider": "Crossref",
                    "source_type": "doi",
                    "identifier": "10.1234/search",
                    "title": "Search Result Research",
                    "description": "Academic publication.",
                    "url": "https://doi.org/10.1234/search",
                }
            ],
            []
        )

        self.client.force_login(self.member_a)

        response = self.client.get(
            reverse("research_library:library_home"),
            {
                "query": "machine learning"
            }
        )

        self.assertEqual(response.status_code, 200)

        mock_search.assert_called_once_with(
            "machine learning"
        )

        self.assertTrue(
            response.context["search_performed"]
        )

        self.assertEqual(
            len(response.context["search_results"]),
            1
        )

    # =====================================
    # TEST 15: ANONYMOUS ACCESS RESTRICTIONS
    # =====================================

    def test_anonymous_members_cannot_access_library(self):

        response = self.client.get(
            reverse("research_library:library_home")
        )

        self.assertEqual(response.status_code, 302)

        response = self.client.post(
            reverse("research_library:save"),
            {
                "source_type": "url",
                "identifier": "https://example.org/new",
                "title": "New Resource"
            }
        )

        self.assertEqual(response.status_code, 302)

class ResearchIngestionTests(TestCase):

    def setUp(self):
        self.member = User.objects.create_user(
            username="ingestion_student",
            email="ingestion@example.com",
            password="TestPass123!",
        )

        pdf_buffer = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.add_metadata({
            "/Title": "Test Research PDF",
            "/Author": "Test Author",
        })
        writer.write(pdf_buffer)

        self.pdf_data = pdf_buffer.getvalue()

        self.resource = ResearchResource.objects.create(
            title="Test Research Paper",
            resource_type="paper",
            uploaded_by=self.member,
            file=SimpleUploadedFile(
                "test_research.pdf",
                self.pdf_data,
                content_type="application/pdf",
            ),
        )

    def tearDown(self):
        if self.resource.file:
            self.resource.file.delete(save=False)

    def test_pdf_metadata_extraction(self):
        from .ingestion import extract_pdf_metadata

        import hashlib

        checksum = hashlib.sha256(self.pdf_data).hexdigest()

        metadata = extract_pdf_metadata(
            self.pdf_data,
            self.resource,
            checksum,
            len(self.pdf_data),
        )

        self.assertEqual(metadata["resource_id"], self.resource.id)
        self.assertEqual(metadata["pdf_title"], "Test Research PDF")
        self.assertEqual(metadata["author"], "Test Author")
        self.assertEqual(metadata["file_format"], "PDF")
        self.assertEqual(metadata["checksum_sha256"], checksum)

    @patch("research_library.ingestion.PdfReader")
    def test_processed_text_extraction_and_normalization(self, mock_reader):
        from .ingestion import extract_processed_document

        page = MagicMock()
        page.extract_text.return_value = (
            "  Research   Commons   \n\n\n  Machine Learning  "
        )

        mock_reader.return_value.pages = [page]

        result = extract_processed_document(
            self.pdf_data,
            self.resource,
            "test-checksum",
        )

        self.assertEqual(result["page_count"], 1)
        self.assertEqual(result["processing_status"], "completed")
        self.assertGreater(result["total_characters"], 0)
        self.assertEqual(
            result["extracted_pages"][0]["text"],
            "Research Commons\n\nMachine Learning",
        )

    def test_invalid_pdf_is_rejected(self):
        from .ingestion import ingest_research_resource

        invalid_resource = ResearchResource.objects.create(
            title="Invalid PDF",
            resource_type="paper",
            uploaded_by=self.member,
            file=SimpleUploadedFile(
                "invalid.pdf",
                b"This is not a PDF file",
                content_type="application/pdf",
            ),
        )

        try:
            with self.assertRaises(ValueError):
                ingest_research_resource(invalid_resource)
        finally:
            invalid_resource.file.delete(save=False)

    @patch("research_library.object_storage.get_minio_client")
    def test_successful_ingestion_uploads_all_three_objects(
        self, mock_get_client
    ):
        from .ingestion import ingest_research_resource

        class FakeMinioClient:
            def __init__(self):
                self.objects = set()
                self.uploaded_objects = []

            def stat_object(self, bucket, object_key):
                if object_key not in self.objects:
                    raise S3Error(
                        None,
                        "NoSuchKey",
                        "Object does not exist",
                        object_key,
                        "",
                        "",
                    )

                return MagicMock(size=100)

            def put_object(
                self,
                bucket_name,
                object_name,
                data,
                length,
                content_type,
                **kwargs,
            ):
                self.objects.add(object_name)
                self.uploaded_objects.append(object_name)

        fake_client = FakeMinioClient()
        mock_get_client.return_value = fake_client

        ingestion = ingest_research_resource(self.resource)

        checksum = ingestion.checksum_sha256

        expected_objects = {
            f"raw/{checksum}.pdf",
            f"metadata/{checksum}.json",
            f"processed/{checksum}.json",
        }

        self.assertEqual(ingestion.status, "completed")
        self.assertEqual(fake_client.objects, expected_objects)
        self.assertEqual(len(fake_client.uploaded_objects), 3)

        self.assertTrue(
            ResearchIngestion.objects.filter(
                resource=self.resource
            ).exists()
        )

    @patch("research_library.object_storage.get_minio_client")
    def test_repeated_ingestion_is_idempotent(self, mock_get_client):
        from .ingestion import ingest_research_resource

        class FakeMinioClient:
            def __init__(self):
                self.objects = set()
                self.uploaded_objects = []

            def stat_object(self, bucket, object_key):
                if object_key not in self.objects:
                    raise S3Error(
                        None,
                        "NoSuchKey",
                        "Object does not exist",
                        object_key,
                        "",
                        "",
                    )

                return MagicMock(size=100)

            def put_object(
                self,
                bucket_name,
                object_name,
                data,
                length,
                content_type,
                **kwargs,
            ):
                self.objects.add(object_name)
                self.uploaded_objects.append(object_name)

        fake_client = FakeMinioClient()
        mock_get_client.return_value = fake_client

        first_result = ingest_research_resource(self.resource)
        second_result = ingest_research_resource(self.resource)
        third_result = ingest_research_resource(self.resource)

        self.assertEqual(first_result.pk, second_result.pk)
        self.assertEqual(second_result.pk, third_result.pk)

        self.assertEqual(
            ResearchIngestion.objects.filter(
                resource=self.resource
            ).count(),
            1,
        )

        self.assertEqual(len(fake_client.uploaded_objects), 3)
