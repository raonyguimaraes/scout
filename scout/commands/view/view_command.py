import logging

import click

from pprint import pprint as pp
from datetime import datetime

from scout.constants import (SEX_MAP, PHENOTYPE_MAP)

from .case import cases

LOG = logging.getLogger(__name__)

@click.command('index', short_help='Display all indexes')
@click.option('-n', '--collection-name')
@click.pass_context
def index(context, collection_name):
    """Show all indexes in the database"""
    LOG.info("Running scout view index")
    adapter = context.obj['adapter']

    i = 0
    for index in adapter.indexes(collection_name):
        click.echo(index)
        i += 1

    if i == 0:
        LOG.info("No indexes found")


@click.command('panels', short_help='Display gene panels')
@click.option('-i', '--institute',
              help='institute id'
)
@click.pass_context
def panels(context, institute):
    """Show all gene panels in the database"""
    LOG.info("Running scout view panels")
    adapter = context.obj['adapter']

    panel_objs = adapter.gene_panels(institute_id = institute)
    if panel_objs.count() == 0:
        LOG.info("No panels found")
        context.abort()
    click.echo("#panel_name\tversion\tnr_genes\tdate")

    for panel_obj in panel_objs:
        click.echo("{0}\t{1}\t{2}\t{3}".format(
            panel_obj['panel_name'],
            str(panel_obj['version']),
            len(panel_obj['genes']),
            str(panel_obj['date'].strftime('%Y-%m-%d'))
        ))

@click.command('users', short_help='Display users')
@click.pass_context
def users(context):
    """Show all users in the database"""
    LOG.info("Running scout view users")
    adapter = context.obj['adapter']

    user_objs = adapter.users()
    if user_objs.count() == 0:
        LOG.info("No users found")
        context.abort()

    click.echo("#name\temail\troles\tinstitutes")
    for user_obj in user_objs:
        click.echo("{0}\t{1}\t{2}\t{3}\t".format(
            user_obj['name'],
            user_obj.get('mail', user_obj['_id']),
            ', '.join(user_obj.get('roles',[])),
            ', '.join(user_obj.get('institutes',[])),
            )
        )

@click.command('individuals', short_help='Display individuals')
@click.option('-i', '--institute',
              help='institute id of related cases'
)
@click.option('--causatives',
              is_flag=True,
              help='Has causative variants'
)
@click.option('-c', '--case-id')
@click.pass_context
def individuals(context, institute, causatives, case_id):
    """Show all individuals from all cases in the database"""
    LOG.info("Running scout view individuals")
    adapter = context.obj['adapter']
    individuals = []

    if case_id:
        case = adapter.case(case_id=case_id)
        if case:
            cases = [case]
        else:
            LOG.info("Could not find case %s", case_id)
            return
    else:
        cases = [case_obj for case_obj in
                 adapter.cases(
                     collaborator=institute,
                     has_causatives=causatives)]
        if len(cases) == 0:
            LOG.info("Could not find cases that match criteria")
            return
        individuals = (ind_obj for case_obj in cases for ind_obj in case_obj['individuals'])

    click.echo("#case_id\tind_id\tdisplay_name\tsex\tphenotype\tmother\tfather")

    for case in cases:
        for ind_obj in case['individuals']:
            ind_info = [
                case['_id'], ind_obj['individual_id'],
                ind_obj['display_name'], SEX_MAP[int(ind_obj['sex'])],
                PHENOTYPE_MAP[ind_obj['phenotype']], ind_obj['mother'],
                ind_obj['father']
                ]
            click.echo('\t'.join(ind_info))
    # if user_objs.count() == 0:
    #     LOG.info("No users found")
    #     context.abort()
    #
    # for user_obj in user_objs:
    #     click.echo("{0}\t{1}\t{2}\t{3}\t".format(
    #         user_obj['name'],
    #         user_obj.get('mail', user_obj['_id']),
    #         ', '.join(user_obj.get('roles',[])),
    #         ', '.join(user_obj.get('institutes',[])),
    #         )
    #     )

@click.command('whitelist', short_help='Display whitelist')
@click.pass_context
def whitelist(context):
    """Show all objects in the whitelist collection"""
    LOG.info("Running scout view users")
    adapter = context.obj['adapter']

    ## TODO add a User interface to the adapter
    for whitelist_obj in adapter.whitelist_collection.find():
        click.echo(whitelist_obj['_id'])


@click.command('institutes', short_help='Display institutes')
@click.pass_context
def institutes(context):
    """Show all institutes in the database"""
    LOG.info("Running scout view institutes")
    adapter = context.obj['adapter']

    institute_objs = adapter.institutes()
    if institute_objs.count() == 0:
        click.echo("No institutes found")
        context.abort()

    click.echo("#institute_id\tdisplay_name")
    for institute_obj in institute_objs:
        click.echo("{0}\t{1}".format(
            institute_obj['_id'],
            institute_obj['display_name']
        ))

@click.command('aliases', short_help='Display genes by aliases')
@click.option('-b', '--build', default='37', type=click.Choice(['37','38']))
@click.pass_context
def aliases(context, build):
    """Show all alias symbols and how they map to ids"""
    LOG.info("Running scout view aliases")
    adapter = context.obj['adapter']

    alias_genes = adapter.genes_by_alias(build=build)
    click.echo("#hgnc_symbol\ttrue_id\thgnc_ids")
    for alias_symbol in alias_genes:
        info = alias_genes[alias_symbol]
        # pp(info)
        click.echo("{0}\t{1}\t{2}\t".format(
            alias_symbol,
            (alias_genes[alias_symbol]['true'] or 'None'),
            ', '.join([str(gene_id) for gene_id in alias_genes[alias_symbol]['ids']])
            )
        )


@click.command('genes', short_help='Display genes')
@click.option('-b', '--build', default='37', type=click.Choice(['37','38']))
# @click.option('-i', '--hgnc-id', type=int)
# @click.option('-s', '--hgnc-symbol')
@click.pass_context
def genes(context, build, hgnc_id, hgnc_symbol):
    """Display genes in the database"""
    LOG.info("Running scout view genes")
    adapter = context.obj['adapter']

    click.echo("Chromosom\tstart\tend\thgnc_id\thgnc_symbol")
    start = datetime.now()
    for gene_obj in adapter.all_genes(build=build):
        click.echo("{0}\t{1}\t{2}\t{3}\t{4}".format(
            gene_obj['chromosome'],
            gene_obj['start'],
            gene_obj['end'],
            gene_obj['hgnc_id'],
            gene_obj['hgnc_symbol'],
        ))
    LOG.info("Time to get all genes: {}".format(datetime.now() - start))

@click.command('diseases', short_help='Display all diseases')
@click.pass_context
def diseases(context):
    """Show all diseases in the database"""
    LOG.info("Running scout view diseases")
    adapter = context.obj['adapter']

    disease_objs = adapter.disease_terms()

    nr_diseases = disease_objs.count()
    if nr_diseases == 0:
       click.echo("No diseases found")
    else:
        click.echo("Disease")
        for disease_obj in adapter.disease_terms():
            click.echo("{0}".format(disease_obj['_id']))
        LOG.info("{0} diseases found".format(nr_diseases))

@click.command('hpo', short_help='Display all hpo terms')
@click.pass_context
def hpo(context):
    """Show all hpo terms in the database"""
    LOG.info("Running scout view hpo")
    adapter = context.obj['adapter']

    click.echo("hpo_id\tdescription")
    for hpo_obj in adapter.hpo_terms():
        click.echo("{0}\t{1}".format(
            hpo_obj.hpo_id,
            hpo_obj.description,
        ))


@click.group()
@click.pass_context
def view(context):
    """
    View objects from the database.
    """
    pass

view.add_command(cases)
view.add_command(panels)
view.add_command(users)
view.add_command(institutes)
view.add_command(genes)
view.add_command(diseases)
view.add_command(hpo)
view.add_command(whitelist)
view.add_command(aliases)
view.add_command(individuals)
view.add_command(index)
