import logging
import urllib.request
from urllib.error import (HTTPError, URLError)

import pybiomart
from scout.constants import CHROMOSOMES

LOG = logging.getLogger(__name__)


def request_file(url):
    """Fetch the file from the given url
    
        Return all lines in a list
    
    Args:
        url(str)
    
    Returns:
        lines(list(str))
    """
    LOG.info("Requesting %s", url)
    try:
        response = urllib.request.urlopen(url)
        data = response.read()      # a `bytes` object
        lines = data.decode('utf-8').split('\n')
    except HTTPError as err:
        LOG.warning("Something went wrong, perhaps the api key is not valid?")
        raise err
    except URLError as err:
        LOG.warning("Something went wrong, are you connected to internet?")
        raise err
    return lines

def fetch_mim_files(api_key, mim2genes=False, mimtitles=False, morbidmap=False, genemap2=False):
    """Fetch the necessary mim files using a api key
    
    Args:
        api_key(str): A api key necessary to fetch mim data
    
    Returns:
        mim_files(dict): A dictionary with the neccesary files
    """

    LOG.info("Fetching OMIM files from https://omim.org/")
    mim2genes_url =  'https://omim.org/static/omim/data/mim2gene.txt'
    mimtitles_url= 'https://data.omim.org/downloads/{0}/mimTitles.txt'.format(api_key)
    morbidmap_url = 'https://data.omim.org/downloads/{0}/morbidmap.txt'.format(api_key)
    genemap2_url =  'https://data.omim.org/downloads/{0}/genemap2.txt'.format(api_key)
        
    mim_files = {}
    mim_urls = {}
    
    if mim2genes is True:
        mim_urls['mim2genes'] = mim2genes_url
    if mimtitles is True:
        mim_urls['mimtitles'] = mimtitles_url
    if morbidmap is True:
        mim_urls['morbidmap'] = morbidmap_url
    if genemap2 is True:
        mim_urls['genemap2'] = genemap2_url

    for file_name in mim_urls:
        url = mim_urls[file_name]
        mim_files[file_name] = request_file(url)

    return mim_files

def fetch_ensembl_genes(build='37'):
    """Fetch the ensembl genes
    
    Args:
        build(str): ['37', '38']
    """
    if build == '37':
        url = 'http://grch37.ensembl.org'
    else:
        url = 'http://www.ensembl.org'
    
    dataset_name = 'hsapiens_gene_ensembl'
    
    dataset = pybiomart.Dataset(name=dataset_name, host=url)
    
    attributes = [
        'chromosome_name',
        'start_position',
        'end_position',
        'ensembl_gene_id',
        'hgnc_symbol',
        'hgnc_id',
    ]
    
    filters = {
        'chromosome_name': CHROMOSOMES,
    }
    
    result = dataset.query(
        attributes = attributes,
        filters = filters
    )
    
    return result

def fetch_ensembl_transcripts(build='37'):
    """Fetch the ensembl genes
    
    Args:
        build(str): ['37', '38']
    """
    LOG.info("Fetching ensembl transcripts build %s ...", build)
    if build == '37':
        url = 'http://grch37.ensembl.org'
    else:
        url = 'http://www.ensembl.org'
    
    dataset_name = 'hsapiens_gene_ensembl'
    
    dataset = pybiomart.Dataset(name=dataset_name, host=url)
    
    attributes = [
        'chromosome_name',
        'ensembl_gene_id',
        'ensembl_transcript_id',
        'transcript_start',
        'transcript_end',
        'refseq_mrna',
		'refseq_mrna_predicted',
		'refseq_ncrna',
    ]
    
    filters = {
        'chromosome_name': CHROMOSOMES,
    }
    
    result = dataset.query(
        attributes = attributes,
        filters = filters
    )
    
    return result

def fetch_ensembl_exons(build='37'):
    """Fetch the ensembl genes
    
    Args:
        build(str): ['37', '38']
    """
    LOG.info("Fetching ensembl exons build %s ...", build)
    if build == '37':
        url = 'http://grch37.ensembl.org'
    else:
        url = 'http://www.ensembl.org'
    
    dataset_name = 'hsapiens_gene_ensembl'
    
    dataset = pybiomart.Dataset(name=dataset_name, host=url)
    
    attributes = [
        'chromosome_name',
        'ensembl_gene_id',
        'ensembl_transcript_id',
        'ensembl_exon_id',
        'exon_chrom_start',
        'exon_chrom_end',
        '5_utr_start',
        '5_utr_end',
        '3_utr_start',
        '3_utr_end',
        'strand',
        'rank'
    ]
    
    filters = {
        'chromosome_name': CHROMOSOMES,
    }
    
    result = dataset.query(
        attributes = attributes,
        filters = filters
    )
    
    return result

def fetch_hgnc():
    """Fetch the hgnc genes file from 
        ftp://ftp.ebi.ac.uk/pub/databases/genenames/new/tsv/hgnc_complete_set.txt
    
    Returns:
        hgnc_gene_lines(list(str))
    """
    url = 'ftp://ftp.ebi.ac.uk/pub/databases/genenames/new/tsv/hgnc_complete_set.txt'
    LOG.info("Fetching HGNC genes")
    
    hgnc_lines = request_file(url)
    
    return hgnc_lines

def fetch_exac_constraint():
    """Fetch the file with exac constraint scores
    
    Returns:
        exac_lines(iterable(str))
    """

    url = ('ftp://ftp.broadinstitute.org/pub/ExAC_release/release0.3/functional_gene_constraint'
           '/fordist_cleaned_exac_r03_march16_z_pli_rec_null_data.txt')
    
    LOG.info("Fetching ExAC genes")
    
    exac_lines = request_file(url)
    
    return exac_lines

def fetch_hpo_files(hpogenes=False, hpoterms=False, phenotype_to_terms=False, hpodisease=False):
    """Fetch the necessary mim files using a api key
    
    Args:
        api_key(str): A api key necessary to fetch mim data
    
    Returns:
        mim_files(dict): A dictionary with the neccesary files
    """

    LOG.info("Fetching HPO information from http://compbio.charite.de")
    base_url = ('http://compbio.charite.de/jenkins/job/hpo.annotations.monthly/'
                'lastStableBuild/artifact/annotation/{}')
    hpogenes_url =  base_url.format('ALL_SOURCES_ALL_FREQUENCIES_diseases_to_genes_to_phenotypes.txt')
    hpoterms_url= base_url.format('ALL_SOURCES_ALL_FREQUENCIES_phenotype_to_genes.txt')
    hpo_phenotype_to_terms_url = base_url.format('ALL_SOURCES_ALL_FREQUENCIES_diseases_to_genes_to_phenotypes.txt')
    hpodisease_url = base_url.format('diseases_to_genes.txt')
        
    hpo_files = {}
    hpo_urls = {}
    
    if hpogenes is True:
        hpo_urls['hpogenes'] = hpogenes_url
    if hpoterms is True:
        hpo_urls['hpoterms'] = hpoterms_url
    if phenotype_to_terms is True:
        hpo_urls['phenotype_to_terms'] = hpo_phenotype_to_terms_url
    if hpodisease is True:
        hpo_urls['hpodisease'] = hpodisease_url

    for file_name in hpo_urls:
        url = hpo_urls[file_name]
        hpo_files[file_name] = request_file(url)

    return hpo_files

