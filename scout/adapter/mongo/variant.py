# -*- coding: utf-8 -*-
# stdlib modules
import logging
import re
import pathlib
import tempfile

from datetime import datetime


# Third party modules
import pymongo

from cyvcf2 import VCF

# Local modules
from scout.parse.variant.headers import (parse_rank_results_header,
                                         parse_vep_header)
from scout.parse.variant.rank_score import parse_rank_score

from scout.parse.variant import parse_variant
from scout.build import build_variant

from scout.utils.coordinates import is_par

from pymongo.errors import DuplicateKeyError
from scout.exceptions import IntegrityError

LOG = logging.getLogger(__name__)


class VariantHandler(object):

    """Methods to handle variants in the mongo adapter"""

    def add_gene_info(self, variant_obj, gene_panels=None):
        """Add extra information about genes from gene panels

        Args:
            variant_obj(dict): A variant from the database
            gene_panels(list(dict)): List of panels from database
        """
        gene_panels = gene_panels or []

        # We need to check if there are any additional information in the gene panels

        # extra_info will hold information from gene panels
        extra_info = {}
        for panel_obj in gene_panels:
            for gene_info in panel_obj['genes']:
                hgnc_id = gene_info['hgnc_id']
                if hgnc_id in extra_info:
                    extra_info[hgnc_id].append(gene_info)
                else:
                    extra_info[hgnc_id] = [gene_info]

        # Loop over the genes in the variant object to add information
        # from hgnc_genes and panel genes
        for variant_gene in variant_obj.get('genes', []):
            hgnc_id = variant_gene['hgnc_id']
            # Get the hgnc_gene
            hgnc_gene = self.hgnc_gene(hgnc_id)

            # Create a dictionary with transcripts information
            transcripts_dict = {}
            if hgnc_gene:
                # Add transcript information from the hgnc gene
                for transcript in hgnc_gene.get('transcripts', []):
                    tx_id = transcript['ensembl_transcript_id']
                    transcripts_dict[tx_id] = transcript

                # Add the transcripts to the gene object
                hgnc_gene['transcripts_dict'] = transcripts_dict

                if hgnc_gene.get('incomplete_penetrance'):
                    variant_gene['omim_penetrance'] = True

            # Get the panel specific information for the gene
            panel_info = extra_info.get(hgnc_id, [])

            # Manually annotated disease associated transcripts
            disease_associated = set()
            # We need to strip the version to compare against others
            disease_associated_no_version = set()
            manual_penetrance = False
            mosaicism = False
            manual_inheritance = set()

            # We need to loop since there can be information from multiple
            # panels
            for gene_info in panel_info:
                # Check if there are manually annotated disease transcripts
                for tx in gene_info.get('disease_associated_transcripts', []):
                    # We remove the version of transcript at this stage
                    stripped = re.sub(r'\.[0-9]', '', tx)
                    disease_associated_no_version.add(stripped)
                    disease_associated.add(tx)
                if gene_info.get('reduced_penetrance'):
                    manual_penetrance = True

                if gene_info.get('mosaicism'):
                    mosaicism = True
                manual_inheritance.update(gene_info.get('inheritance_models', []))

            variant_gene['disease_associated_transcripts'] = list(disease_associated)
            variant_gene['manual_penetrance'] = manual_penetrance
            variant_gene['mosaicism'] = mosaicism
            variant_gene['manual_inheritance'] = list(manual_inheritance)

            # Now add the information from hgnc and panels
            # to the transcripts on the variant

            # First loop over the variants transcripts
            for transcript in variant_gene.get('transcripts', []):
                tx_id = transcript['transcript_id']
                if tx_id in transcripts_dict:
                    hgnc_transcript = transcripts_dict[tx_id]
                    # If the transcript has a ref seq identifier we add that
                    # to the variants transcript
                    if 'refseq_ids' in hgnc_transcript:
                        refseq_ids = hgnc_transcript['refseq_ids']
                        transcript['refseq_ids'] = refseq_ids

                        # Check if any of the refseq ids are disease associated
                        for refseq_id in refseq_ids:
                            if refseq_id in disease_associated_no_version:
                                transcript['is_disease_associated'] = True

                    if hgnc_transcript.get('is_primary'):
                        transcript['is_primary'] = True

            variant_gene['common'] = hgnc_gene

            # Add the associated disease terms
            variant_gene['disease_terms'] = self.disease_terms(hgnc_id)

        return variant_obj

    def variants(self, case_id, query=None, variant_ids=None, category='snv',
                 nr_of_variants=10, skip=0, sort_key='variant_rank'):
        """Returns variants specified in question for a specific case.

        If skip not equal to 0 skip the first n variants.

        Arguments:
            case_id(str): A string that represents the case
            query(dict): A dictionary with querys for the database
            variant_ids(List[str])
            category(str): 'sv' or 'snv' or 'cancer'
            nr_of_variants(int): if -1 return all variants
            skip(int): How many variants to skip
            sort_key: 'variant_rank' or 'rank_score'

        Yields:
            result(Iterable[Variant])
        """
        LOG.info("Fetching variants from {0}".format(case_id))

        if variant_ids:
            nr_of_variants = len(variant_ids)

        elif nr_of_variants == -1:
            nr_of_variants = 0 # This will return all variants

        else:
            nr_of_variants = skip + nr_of_variants

        mongo_query = self.build_query(case_id, query=query,
                                       variant_ids=variant_ids,
                                       category=category)

        sorting = []
        if sort_key == 'variant_rank':
            sorting = [('variant_rank', pymongo.ASCENDING)]
        if sort_key == 'rank_score':
            sorting = [('rank_score', pymongo.DESCENDING)]

        result = self.variant_collection.find(
            mongo_query,
            skip=skip,
            limit=nr_of_variants
        ).sort(sorting)

        return result

    def variant(self, document_id, gene_panels=None, case_id=None):
        """Returns the specified variant.

           Arguments:
               document_id : A md5 key that represents the variant or "variant_id"
               gene_panels(List[GenePanel])
               case_id (str): case id (will search with "variant_id")

           Returns:
               variant_object(Variant): A odm variant object
        """
        if case_id:
            # search for a variant in a case
            variant_obj = self.variant_collection.find_one({
                'case_id': case_id,
                'variant_id': document_id,
            })
        else:
            # search with a unique id
            variant_obj = self.variant_collection.find_one({'_id': document_id})
        if variant_obj:
            variant_obj = self.add_gene_info(variant_obj, gene_panels)
            if variant_obj['chromosome'] in ['X', 'Y']:
                ## TODO add the build here
                variant_obj['is_par'] = is_par(variant_obj['chromosome'],
                                               variant_obj['position'])
        return variant_obj

    def get_causatives(self, institute_id):
        """Return all causative variants for an institute

            Args:
                institute_id(str)

            Yields:
                str: variant document id
        """
        query = self.case_collection.aggregate([
            {'$match': {'collaborators': institute_id, 'causatives': {'$exists': True}}},
            {'$unwind': '$causatives'},
            {'$group': {'_id': '$causatives'}}
        ])
        return [item['_id'] for item in query]

    def check_causatives(self, case_obj=None, institute_obj=None):
        """Check if there are any variants that are previously marked causative

            Loop through all variants that are marked 'causative' for an
            institute and check if any of the variants are present in the
            current case.

            Args:
                case_obj (dict): A Case object
                institute_obj (dict): check across the whole institute

            Returns:
                causatives(iterable(Variant))
        """
        institute_id = case_obj['owner'] if case_obj else institute_obj['_id']
        institute_causative_variant_ids = self.get_causatives(institute_id)
        if len(institute_causative_variant_ids) == 0:
            return []

        if case_obj:
            # exclude variants that are marked causative in "case_obj"
            case_causative_ids = set(case_obj.get('causatives', []))
            institute_causative_variant_ids = list(
                set(institute_causative_variant_ids).difference(case_causative_ids)
            )

        # convert from unique ids to general "variant_id"
        query = self.variant_collection.find(
            {'_id': {'$in': institute_causative_variant_ids}},
            {'variant_id': 1}
        )
        positional_variant_ids = [item['variant_id'] for item in query]

        filters = {'variant_id': {'$in': positional_variant_ids}}
        if case_obj:
            filters['case_id'] = case_obj['_id']
        else:
            filters['institute'] = institute_obj['_id']
        return self.variant_collection.find(filters)

    def update_variant(self, variant_obj):
        """Update one variant document in the database.

        Args:
            variant_obj(dict)

        Returns:
            new_variant(dict)
        """
        new_variant = self.variant_collection.find_one_and_replace(
            {'_id': variant_obj['_id']},
            variant_obj,
            return_document=pymongo.ReturnDocument.AFTER
        )
        return new_variant

    def update_variants(self, case_obj, variant_type='clinical', category='snv'):
        """Adds extra information on variants.

        Add a variant rank based on the rank score
        Add extra information on compounds

            Args:
                case_obj(Case)
                variant_type(str)
        """
        # Get all variants sorted by rank score
        variants = self.variant_collection.find({
            'case_id': case_obj['_id'],
            'category': category,
            'variant_type': variant_type,
        }).sort('rank_score', pymongo.DESCENDING)

        LOG.info("Updating variant_rank for all variants")

        # Update the information on all compounds
        for index, variant in enumerate(variants):
            # This is a list with the updated compound documents
            # compound_objs = self.update_compounds(variant)
            self.variant_collection.find_one_and_update(
                {'_id': variant['_id']},
                {
                    '$set': {
                        'variant_rank': index + 1,
                        # 'compounds': compound_objs,
                    }
                }
            )

        LOG.info("Updating variant_rank done")

    def update_compounds(self, variant, variant_objs = None):
        """Update compounds for a variant.
        
        This will add all the necessary information of a variant on a compound object.
        
        Args:
            variant(scout.models.Variant)
            variant_objs(dict): A dictionary with _ids as keys and variant objs as values.
        
        Returns:
            compound_objs(list(dict)): A dictionary with updated compound objects.
        
        """
        compound_objs = []
        for compound in variant.get('compounds', []):
            not_loaded = True
            gene_objs = []
            # Check if the compound variant exists
            if variant_objs:
                variant_obj = variant_objs.get(compound['variant'])
            else:
                variant_obj = self.variant_collection.find_one({'_id': compound['variant']})
            if not variant_obj:
                continue
            # If the variant exosts we try to collect as much info as possible
            not_loaded = False
            compound['rank_score'] = variant_obj['rank_score']
            for gene in variant_obj.get('genes', []):
                gene_obj = {
                    'hgnc_id': gene['hgnc_id'],
                    'hgnc_symbol': gene.get('hgnc_symbol'),
                    'region_annotation': gene.get('region_annotation'),
                    'functional_annotation': gene.get('functional_annotation'),
                }
                gene_objs.append(gene_obj)

            compound['not_loaded'] = not_loaded
            compound['genes'] = gene_objs
            compound_objs.append(compound)
        return compound_objs

    def add_variant_rank(self, case_obj, variant_type='clinical', category='snv'):
        """Add the variant rank for all inserted variants.

            Args:
                case_obj(Case)
                variant_type(str)
        """
        variants = self.variant_collection.find(
            {
                'case_id': case_obj['_id'],
                'category': category,
                'variant_type': variant_type,
            },
            {'_id':1}
        ).sort('rank_score', pymongo.DESCENDING)

        LOG.info("Updating variant_rank for all variants")
        for index, variant in enumerate(variants):
            self.variant_collection.find_one_and_update(
                {'_id': variant['_id']},
                {'$set': {'variant_rank': index + 1}}
            )
        LOG.info("Updating variant_rank done")

    def other_causatives(self, case_obj, variant_obj):
        """Find the same variant in other cases marked causative."""
        # variant id without "*_[variant_type]"
        variant_id = variant_obj['display_name'].rsplit('_', 1)[0]

        institute_causatives = self.get_causatives(variant_obj['institute'])
        for causative_id in institute_causatives:
            other_variant = self.variant(causative_id)
            not_same_case = other_variant['case_id'] != case_obj['_id']
            same_variant = other_variant['display_name'].startswith(variant_id)
            if not_same_case and same_variant:
                yield other_variant

    def delete_variants(self, case_id, variant_type, category=None):
        """Delete variants of one type for a case

            This is used when a case is reanalyzed

            Args:
                case_id(str): The case id
                variant_type(str): 'research' or 'clinical'
        """
        LOG.info("Deleting old {0} {1} variants for case {1}".format(
                    variant_type, category, case_id))
        query = {'case_id': case_id, 'variant_type': variant_type}
        if category:
            query['category'] = category
        result = self.variant_collection.delete_many(query)
        LOG.info("{0} variants deleted".format(result.deleted_count))

    def load_variant(self, variant_obj):
        """Load a variant object

        Args:
            variant_obj(dict)

        Returns:
            inserted_id
        """
        LOG.debug("Loading variant %s", variant_obj['_id'])
        try:
            result = self.variant_collection.insert_one(variant_obj)
        except DuplicateKeyError as err:
            raise IntegrityError("Variant %s already exists in database", variant_obj['_id'])
        return result.inserted_id

    def load_variants(self, case_obj, variant_type='clinical', category='snv',
                      rank_threshold=None, chrom=None, start=None, end=None,
                      gene_obj=None):
        """Load variants for a case into scout.

        Load the variants for a specific analysis type and category into scout.
        If no region is specified, load all variants above rank score threshold
        If region or gene is specified, load all variants from that region
        disregarding variant rank(if not specified)

        Args:
            case_obj(dict): A case from the scout database
            variant_type(str): 'clinical' or 'research'. Default: 'clinical'
            category(str): 'snv' or 'sv'. Default: 'snv'
            rank_threshold(float): Only load variants above this score. Default: 0
            chrom(str): Load variants from a certain chromosome
            start(int): Specify the start position
            end(int): Specify the end position
            gene_obj(dict): A gene object from the database

        Returns:
            nr_inserted(int)
        """
        institute_obj = self.institute(institute_id=case_obj['owner'])
        gene_to_panels = self.gene_to_panels()
        hgncid_to_gene = self.hgncid_to_gene()

        variant_file = None
        if variant_type == 'clinical':
            if category == 'snv':
                variant_file = case_obj['vcf_files'].get('vcf_snv')
            elif category == 'sv':
                variant_file = case_obj['vcf_files'].get('vcf_sv')
            elif category == 'cancer':
                # Currently this implies a paired tumor normal
                variant_file = case_obj['vcf_files'].get('vcf_cancer')
        elif variant_type == 'research':
            if category == 'snv':
                variant_file = case_obj['vcf_files'].get('vcf_snv_research')
            elif category == 'sv':
                variant_file = case_obj['vcf_files'].get('vcf_sv_research')
            elif category == 'cancer':
                variant_file = case_obj['vcf_files'].get('vcf_cancer_research')

        if not variant_file:
            raise SyntaxError("Vcf file does not seem to exist")

        vcf_obj = VCF(variant_file)

        # Parse the neccessary headers from vcf file
        rank_results_header = parse_rank_results_header(vcf_obj)
        vep_header = parse_vep_header(vcf_obj)

        # Dictionary for cancer analysis
        sample_info = {}
        if category == 'cancer':
            for ind in case_obj['individuals']:
                if ind['phenotype'] == 2:
                    sample_info[ind['individual_id']] = 'case'
                else:
                    sample_info[ind['individual_id']] = 'control'

        # This is a dictionary to tell where ind are in vcf
        individual_positions = {}
        for i, ind in enumerate(vcf_obj.samples):
            individual_positions[ind] = i

        # Check if a region scould be uploaded
        region = ""
        if gene_obj:
            chrom = gene_obj['chromosome']
            # Add same padding as VEP
            start = max(gene_obj['start'] - 5000, 0)
            end = gene_obj['end'] + 5000
        if chrom:
            rank_threshold = rank_threshold or -1000
            if not (start and end):
                raise SyntaxError("Specify chrom start and end")
            region = "{0}:{1}-{2}".format(chrom, start, end)
        else:
            rank_threshold = rank_threshold or 0

        LOG.info("Start inserting variants into database")
        start_insertion = datetime.now()
        start_five_thousand = datetime.now()
        # These are the number of parsed varaints
        nr_variants = 0
        # These are the number of variants that meet the criteria and gets
        # inserted
        nr_inserted = 0
        # This is to keep track of the inserted variants
        inserted = 1

        try:
            for nr_variants, variant in enumerate(vcf_obj(region)):
                mt_variant = 'MT' in variant.CHROM
                rank_score = parse_rank_score(variant.INFO.get('RankScore'), case_obj['_id'])
                if (rank_score is None) or (rank_score > rank_threshold) or mt_variant:
                    # Parse the vcf variant
                    parsed_variant = parse_variant(
                        variant=variant,
                        case=case_obj,
                        variant_type=variant_type,
                        rank_results_header=rank_results_header,
                        vep_header=vep_header,
                        individual_positions=individual_positions,
                        category=category,
                    )

                    # Build the variant object
                    variant_obj = build_variant(
                        variant=parsed_variant,
                        institute_id=institute_obj['_id'],
                        gene_to_panels=gene_to_panels,
                        hgncid_to_gene=hgncid_to_gene,
                        sample_info=sample_info
                    )
                    
                    # Load the variant object
                    try:
                        self.load_variant(variant_obj)
                        nr_inserted += 1
                    except IntegrityError as error:
                        pass

                    if (nr_variants != 0 and nr_variants % 5000 == 0):
                        LOG.info("%s variants parsed", str(nr_variants))
                        LOG.info("Time to parse variants: %s",
                                    (datetime.now() - start_five_thousand))
                        start_five_thousand = datetime.now()

                    if (nr_inserted != 0 and (nr_inserted * inserted) % (1000 * inserted) == 0):
                        LOG.info("%s variants inserted", nr_inserted)
                        inserted += 1

        except Exception as error:
            LOG.exception('unexpected error')
            LOG.warning("Deleting inserted variants")
            self.delete_variants(case_obj['_id'], variant_type)
            raise error

        self.update_variants(case_obj, variant_type, category=category)
        
        ## If all variants of a region are loaded we need to update the compounds of that region
        if region:
            LOG.info("Updating compound information for all variants in region")
            # Get all variants in a region
            query = self.build_query(
                        case_id=case_obj['_id'],
                        query={
                            'variant_type': variant_type,
                            'chrom': chrom,
                            'start': start,
                            'end': end,
                        },
                        category=category
                    )
            res = self.variant_collection.find(query)
            # Store them in a dictionary for faster access
            # This should not be dangerous since we know there is a limited number of variants for
            # a region
            variants = {var['_id']: var for var in res}
            # Get a iterable with variant objs. This is to avoid to iterate over a dictionary that
            # will be updated during iteration
            variant_objs = variants.values()
            
            # Now update the compound information for all variants in the region
            for variant_obj in variant_objs:
                if not variant_obj.get('compounds'):
                    continue

                # get a list with updated compounds
                new_compounds = self.update_compounds(variant_obj, variants)
                # Update the variant
                variant_obj['compounds'] = new_compounds

                # sort compounds on combined rank score
                variant_obj['compounds'] = sorted(variant_obj['compounds'],
                                              key=lambda compound: -compound['combined_score'])
                # Store the information in the database
                self.update_variant(variant_obj)

        LOG.info("Nr variants inserted: %s", nr_inserted)

        return nr_inserted

    def overlapping(self, variant_obj):
        """Return ovelapping variants.

        Look at the genes that a variant overlapps to get coordinates.
        Then return all variants that overlap these coordinates.

        If variant_obj is sv it will return the overlapping snvs and oposite

        Args:
            variant_obj(dict)

        Returns:
            variants(iterable(dict))
        """
        category = 'snv' if variant_obj['category'] == 'sv' else 'sv'

        region_start = None
        region_end = None
        chromosome = variant_obj['chromosome']

        for gene_id in variant_obj['hgnc_ids']:
            gene_obj = self.hgnc_gene(gene_id)
            if not gene_obj:
                continue
            
            gene_start = gene_obj['start']
            gene_end = gene_obj['end']
            if not region_start:
                region_start = gene_start
            else:
                if gene_start < region_start:
                    region_start = gene_start
            if not region_end:
                region_end = gene_end
            else:
                if gene_end > region_end:
                    region_end = gene_end

        query = self.build_query(
            case_id=variant_obj['case_id'],
            query={
                'variant_type': variant_obj['variant_type'],
                'chrom': chromosome,
                'start': region_start,
                'end': region_end,
            },
            category=category
        )

        sort_key = [('rank_score', pymongo.DESCENDING)]
        variants = self.variant_collection.find(query).sort(sort_key)

        return variants

    def get_region_vcf(self, case_obj, chrom=None, start=None, end=None,
                       gene_obj=None, variant_type='clinical', category='snv',
                       rank_threshold=None):
        """Produce a reduced vcf with variants from the specified coordinates
           This is used for the alignment viewer.

        Args:
            case_obj(dict): A case from the scout database
            variant_type(str): 'clinical' or 'research'. Default: 'clinical'
            category(str): 'snv' or 'sv'. Default: 'snv'
            rank_threshold(float): Only load variants above this score. Default: 5
            chrom(str): Load variants from a certain chromosome
            start(int): Specify the start position
            end(int): Specify the end position
            gene_obj(dict): A gene object from the database

        Returns:
            file_name(str): Path to the temporary file
        """
        rank_threshold = rank_threshold or -100

        variant_file = None
        if variant_type == 'clinical':
            if category == 'snv':
                variant_file = case_obj['vcf_files'].get('vcf_snv')
            elif category == 'sv':
                variant_file = case_obj['vcf_files'].get('vcf_sv')
        elif variant_type == 'research':
            if category == 'snv':
                variant_file = case_obj['vcf_files'].get('vcf_snv_research')
            elif category == 'sv':
                variant_file = case_obj['vcf_files'].get('vcf_sv_research')

        if not variant_file:
            raise SyntaxError("Vcf file does not seem to exist")

        vcf_obj = VCF(variant_file)
        region = ""

        if gene_obj:
            chrom = gene_obj['chromosome']
            start = gene_obj['start']
            end = gene_obj['end']

        if chrom:
            if (start and end):
                region = "{0}:{1}-{2}".format(chrom, start, end)
            else:
                region = "{0}".format(chrom)

        else:
            rank_threshold = rank_threshold or 5

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as temp:
            file_name = pathlib.Path(temp.name)
            for header_line in vcf_obj.raw_header.split('\n'):
                if len(header_line) > 3:
                    temp.write(header_line + '\n')
            for variant in vcf_obj(region):
                temp.write(str(variant))

        return file_name
