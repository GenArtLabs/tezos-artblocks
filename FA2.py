##
## ## Introduction
##
## See the FA2 standard definition:
## <https://gitlab.com/tzip/tzip/-/blob/master/proposals/tzip-12/>
##
## See more examples/documentation at
## <https://gitlab.com/smondet/fa2-smartpy/> and
## <https://assets.tqtezos.com/docs/token-contracts/fa2/1-fa2-smartpy/>.
##
import smartpy as sp


def bytes_of_nat(params):
    c   = sp.map({x : sp.bytes(hex(x + 48)) for x in range(0, 10)})
    x   = sp.local('x', params)
    res = sp.local('res', [])
    sp.if x.value == 0:
        res.value.push(c[x.value % 10])
    sp.while 0 < x.value:
        res.value.push(c[x.value % 10])
        x.value //= 10
    return sp.concat(res.value)
##
## ## Meta-Programming Configuration
##
## The `FA2_config` class holds the meta-programming configuration.
##
class FA2_config:
    def __init__(self,
                 debug_mode                         = False,
                 readable                           = True,
                 force_layouts                      = True,
                 support_operator                   = True,
                 allow_self_transfer                = False,
                 price                              = 1000000,
                 max_editions                       = 2,
                 base_uri                       = "https://open-artblocks.herokuapp.com/api/",
                 ):

        if debug_mode:
            self.my_map = sp.map
        else:
            self.my_map = sp.big_map
        # The option `debug_mode` makes the code generation use
        # regular maps instead of big-maps, hence it makes inspection
        # of the state of the contract easier.

        self.price = price
        self.max_editions = max_editions
        self.base_uri = base_uri

        self.readable = readable
        # The `readable` option is a legacy setting that we keep around
        # only for benchmarking purposes.
        #
        # User-accounts are kept in a big-map:
        # `(user-address * token-id) -> ownership-info`.
        #
        # For the Babylon protocol, one had to use `readable = False`
        # in order to use `PACK` on the keys of the big-map.

        self.force_layouts = force_layouts
        # The specification requires all interface-fronting records
        # and variants to be *right-combs;* we keep
        # this parameter to be able to compare performance & code-size.

        self.support_operator = support_operator
        # The operator entry-points always have to be there, but there is
        # definitely a use-case for having them completely empty (saving
        # storage and gas when `support_operator` is `False).

        self.add_mutez_transfer = True
        # Add an entry point for the administrator to transfer tez potentially
        # in the contract's balance.

        self.allow_self_transfer = allow_self_transfer
        # Authorize call of `transfer` entry_point from self
        name = "FA2"
        if debug_mode:
            name += "-debug"
        if not readable:
            name += "-no_readable"
        if not force_layouts:
            name += "-no_layout"
        if not support_operator:
            name += "-no_ops"
        if allow_self_transfer:
            name += "-self_transfer"
        self.name = name

## ## Auxiliary Classes and Values
##
## The definitions below implement SmartML-types and functions for various
## important types.
##
token_id_type = sp.TNat

class Error_message:
    def __init__(self, config):
        self.config = config
        self.prefix = "FA2_"
    def make(self, s): return (self.prefix + s)
    def token_undefined(self):       return self.make("TOKEN_UNDEFINED")
    def insufficient_balance(self):  return self.make("INSUFFICIENT_BALANCE")
    def not_operator(self):          return self.make("NOT_OPERATOR")
    def not_owner(self):             return self.make("NOT_OWNER")
    def bad_value(self):             return self.make("BAD_VALUE")
    def max_editions_reached(self):  return self.make("MAX_EDITIONS_REACHED")
    def operators_unsupported(self): return self.make("OPERATORS_UNSUPPORTED")
    def not_admin(self):             return self.make("NOT_ADMIN")
    def not_admin_or_operator(self): return self.make("NOT_ADMIN_OR_OPERATOR")
    def paused(self):                return self.make("PAUSED")
    def locked(self):                return self.make("LOCKED")
    def bad_amount(self):            return self.make("BAD_QUANTITY")
    def sale_started(self):          return self.make("SALE_STARTED")

## The current type for a batched transfer in the specification is as
## follows:
##
## ```ocaml
## type transfer = {
##   from_ : address;
##   txs: {
##     to_ : address;
##     token_id : token_id;
##     amount : nat;
##   } list
## } list
## ```
##
## This class provides helpers to create and force the type of such elements.
## It uses the `FA2_config` to decide whether to set the right-comb layouts.
class Batch_transfer:
    def __init__(self, config):
        self.config = config
    def get_transfer_type(self):
        tx_type = sp.TRecord(to_ = sp.TAddress,
                             token_id = token_id_type,
                             amount = sp.TNat)
        if self.config.force_layouts:
            tx_type = tx_type.layout(
                ("to_", ("token_id", "amount"))
            )
        transfer_type = sp.TRecord(from_ = sp.TAddress,
                                   txs = sp.TList(tx_type)).layout(
                                       ("from_", "txs"))
        return transfer_type
    def get_type(self):
        return sp.TList(self.get_transfer_type())
    def item(self, from_, txs):
        v = sp.record(from_ = from_, txs = txs)
        return sp.set_type_expr(v, self.get_transfer_type())
##
## `Operator_param` defines type types for the `%update_operators` entry-point.
class Operator_param:
    def __init__(self, config):
        self.config = config
    def get_type(self):
        t = sp.TRecord(
            owner = sp.TAddress,
            operator = sp.TAddress,
            token_id = token_id_type)
        if self.config.force_layouts:
            t = t.layout(("owner", ("operator", "token_id")))
        return t
    def make(self, owner, operator, token_id):
        r = sp.record(owner = owner,
                      operator = operator,
                      token_id = token_id)
        return sp.set_type_expr(r, self.get_type())

## The link between operators and the addresses they operate is kept
## in a *lazy set* of `(owner × operator × token-id)` values.
##
## A lazy set is a big-map whose keys are the elements of the set and
## values are all `Unit`.
class Operator_set:
    def __init__(self, config):
        self.config = config
    def inner_type(self):
        return sp.TRecord(owner = sp.TAddress,
                          operator = sp.TAddress,
                          token_id = token_id_type
                          ).layout(("owner", ("operator", "token_id")))
    def key_type(self):
        if self.config.readable:
            return self.inner_type()
        else:
            return sp.TBytes
    def make(self):
        return self.config.my_map(tkey = self.key_type(), tvalue = sp.TUnit)
    def make_key(self, owner, operator, token_id):
        metakey = sp.record(owner = owner,
                            operator = operator,
                            token_id = token_id)
        metakey = sp.set_type_expr(metakey, self.inner_type())
        if self.config.readable:
            return metakey
        else:
            return sp.pack(metakey)
    def add(self, set, owner, operator, token_id):
        set[self.make_key(owner, operator, token_id)] = sp.unit
    def remove(self, set, owner, operator, token_id):
        del set[self.make_key(owner, operator, token_id)]
    def is_member(self, set, owner, operator, token_id):
        return set.contains(self.make_key(owner, operator, token_id))

class Balance_of:
    def request_type():
        return sp.TRecord(
            owner = sp.TAddress,
            token_id = token_id_type).layout(("owner", "token_id"))
    def response_type():
        return sp.TList(
            sp.TRecord(
                request = Balance_of.request_type(),
                balance = sp.TNat).layout(("request", "balance")))
    def entry_point_type():
        return sp.TRecord(
            callback = sp.TContract(Balance_of.response_type()),
            requests = sp.TList(Balance_of.request_type())
        ).layout(("requests", "callback"))

class Token_meta_data:
    def __init__(self, config):
        self.config = config

    def get_type(self):
        return sp.TRecord(token_id = sp.TNat, token_info = sp.TMap(sp.TString, sp.TBytes))

    def set_type_and_layout(self, expr):
        sp.set_type(expr, self.get_type())

## The set of all tokens is represented by a `nat` if we assume that token-ids
## are consecutive, or by an actual `(set nat)` if not.
##
## - Knowing the set of tokens is useful for throwing accurate error messages.
## - Previous versions of the specification required this set for functional
##   behavior (operators interface had to deal with “all tokens”).
class Token_id_set:
    def __init__(self, config):
        self.config = config
    def empty(self):
        return sp.nat(0)
    def add(self, totalTokens, tokenID):
        sp.verify(totalTokens == tokenID, message = "Token-IDs should be consecutive")
        totalTokens.set(tokenID + 1)
    def contains(self, totalTokens, tokenID):
        return (tokenID < totalTokens)
    def cardinal(self, totalTokens):
        return totalTokens

##
## ## Implementation of the Contract
##
## `mutez_transfer` is an optional entry-point, hence we define it “outside” the
## class:
def mutez_transfer(contract, params):
    sp.verify(sp.sender == contract.data.administrator)
    sp.set_type(params.destination, sp.TAddress)
    sp.set_type(params.amount, sp.TMutez)
    sp.verify(params.amount <= sp.balance)
    sp.send(params.destination, params.amount)
##
## The `FA2` class builds a contract according to an `FA2_config` and an
## administrator address.
## It is inheriting from `FA2_core` which implements the strict
## standard and a few other classes to add other common features.
##
## - We see the use of
##   [`sp.entry_point`](https://smartpy.io/docs/introduction/entry_points)
##   as a function instead of using annotations in order to allow
##   optional entry points.
## - The storage field `metadata_string` is a placeholder, the build
##   system replaces the field annotation with a specific version-string, such
##   as `"version_20200602_tzip_b916f32"`: the version of FA2-smartpy and
##   the git commit in the TZIP [repository](https://gitlab.com/tzip/tzip) that
##   the contract should obey.
class FA2_core(sp.Contract):
    def __init__(self, config, metadata, **extra_storage):
        self.config = config
        self.error_message = Error_message(self.config)
        self.operator_set = Operator_set(self.config)
        self.operator_param = Operator_param(self.config)
        self.token_id_set = Token_id_set(self.config)
        # TODO understand self.ledger_key = Ledger_key(self.config)
        self.token_meta_data = Token_meta_data(self.config)
        self.batch_transfer    = Batch_transfer(self.config)
        if  self.config.add_mutez_transfer:
            self.transfer_mutez = sp.entry_point(mutez_transfer)
        self.add_flag("initial-cast")
        self.exception_optimization_level = "default-line"
        self.init(
            ledger = self.config.my_map(tkey = sp.TNat, tvalue = sp.TAddress),
            hashes = self.config.my_map(tkey = sp.TNat, tvalue = sp.TBytes),
            operators = self.operator_set.make(),
            all_tokens = self.token_id_set.empty(),
            metadata = metadata,
            price = sp.mutez(self.config.price),
            max_editions = self.config.max_editions,
            script = sp.string(""),
            base_uri = sp.utils.bytes_of_string(self.config.base_uri),
            **extra_storage
        )

    @sp.entry_point
    def transfer(self, params):
        sp.set_type(params, self.batch_transfer.get_type())
        sp.for transfer in params:
           sp.for tx in transfer.txs:

                sender_verify = (
                    (transfer.from_ == sp.sender) |
                    self.operator_set.is_member(self.data.operators,
                        transfer.from_,
                        sp.sender,
                        tx.token_id)
                )
                message = self.error_message.not_operator()

                if self.config.allow_self_transfer:
                    sender_verify |= (sp.sender == sp.self_address)
                sp.verify(sender_verify, message = message)
                sp.verify(
                    self.data.hashes.contains(tx.token_id),
                    message = self.error_message.token_undefined()
                )
                sp.verify(tx.amount <= 1, message = self.error_message.insufficient_balance())

                sp.if (tx.amount == 1):

                    sp.verify(
                        (self.data.ledger[tx.token_id] == transfer.from_),
                        message = self.error_message.insufficient_balance())
                    self.data.ledger[tx.token_id] = tx.to_
                sp.else:
                    pass

    @sp.entry_point
    def balance_of(self, params):
        sp.set_type(params, Balance_of.entry_point_type())
        def f_process_request(req):
            sp.verify(self.data.hashes.contains(req.token_id), message = self.error_message.token_undefined())
            sp.if self.data.ledger[req.token_id] == req.owner:
                sp.result(
                    sp.record(
                        request = sp.record(
                            owner = sp.set_type_expr(req.owner, sp.TAddress),
                            token_id = sp.set_type_expr(req.token_id, sp.TNat)),
                        balance = 1))
            sp.else:
                sp.result(
                    sp.record(
                        request = sp.record(
                            owner = sp.set_type_expr(req.owner, sp.TAddress),
                            token_id = sp.set_type_expr(req.token_id, sp.TNat)),
                        balance = 0))
        res = sp.local("responses", params.requests.map(f_process_request))
        destination = sp.set_type_expr(params.callback, sp.TContract(Balance_of.response_type()))
        sp.transfer(res.value, sp.mutez(0), destination)

    @sp.offchain_view(pure = True)
    def get_balance(self, req):
        """This is the `get_balance` view defined in TZIP-12."""
        sp.set_type(
            req, sp.TRecord(
                owner = sp.TAddress,
                token_id = sp.TNat
            ).layout(("owner", "token_id")))
        sp.verify(self.data.hashes.contains(req.token_id), message = self.error_message.token_undefined())
        sp.if self.data.ledger[req.token_id] == req.owner:
            sp.result(1)
        sp.else:
            sp.result(0)

    @sp.entry_point
    def update_operators(self, params):
        sp.set_type(params, sp.TList(
            sp.TVariant(
                add_operator = self.operator_param.get_type(),
                remove_operator = self.operator_param.get_type()
            )
        ))
        if self.config.support_operator:
            sp.for update in params:
                with update.match_cases() as arg:
                    with arg.match("add_operator") as upd:
                        sp.verify(upd.owner == sp.sender, message = self.error_message.not_owner())
                        self.operator_set.add(self.data.operators,
                                              upd.owner,
                                              upd.operator,
                                              upd.token_id)
                    with arg.match("remove_operator") as upd:
                        sp.verify(upd.owner == sp.sender, message = self.error_message.not_owner())
                        self.operator_set.remove(self.data.operators,
                                                 upd.owner,
                                                 upd.operator,
                                                 upd.token_id)
        else:
            sp.failwith(self.error_message.operators_unsupported())

    @sp.entry_point
    def set_mint_parameters(self, params):
        sp.verify(self.is_administrator(sp.sender), message = self.error_message.not_admin())
        sp.verify(self.data.all_tokens <= 1, message = self.error_message.sale_started())
        sp.set_type(
            params, sp.TRecord(
                price = sp.TMutez,
                max_editions = sp.TNat
            ).layout(("price", "max_editions")))
        sp.verify(self.data.all_tokens <= params.max_editions, message = self.error_message.bad_amount())
        self.data.max_editions = params.max_editions
        self.data.price = params.price

    # this is not part of the standard but can be supported through inheritance.
    def is_paused(self):
        return sp.bool(False)

    # this is not part of the standard but can be supported through inheritance.
    def is_administrator(self, sender):
        return sp.bool(False)

class FA2_administrator(FA2_core):
    def is_administrator(self, sender):
        return sender == self.data.administrator

    @sp.entry_point
    def set_administrator(self, params):
        sp.verify(self.is_administrator(sp.sender), message = self.error_message.not_admin())
        self.data.administrator = params

class FA2_pause(FA2_core):
    def is_paused(self):
        return self.data.paused

    @sp.entry_point
    def set_pause(self, params):
        sp.verify(self.is_administrator(sp.sender), message = self.error_message.not_admin())
        self.data.paused = params

class FA2_lock(FA2_core):
    def is_locked(self):
        return self.data.locked

    @sp.entry_point
    def lock(self):
        sp.verify(self.is_administrator(sp.sender), message = self.error_message.not_admin())
        self.data.locked = sp.bool(True)

class FA2_mint(FA2_core):
    @sp.entry_point
    def mint(self, amount):
        sp.set_type(amount, sp.TInt)
        sp.verify(amount > 0, message = self.error_message.bad_amount())

        sp.verify(~ self.is_paused(), message = self.error_message.paused())

        nat_amount = sp.as_nat(amount, message = self.error_message.bad_amount())
        sp.verify(sp.amount == sp.mul(self.data.price, nat_amount), message = self.error_message.bad_value())
        sp.verify(self.data.all_tokens + nat_amount <= self.data.max_editions, message = self.error_message.max_editions_reached())

        i = sp.compute(amount)
        sp.while i > 0:
            token_id = sp.compute(self.data.all_tokens)
            sp.verify(token_id < self.data.max_editions, message = self.error_message.max_editions_reached())

            token_hash = sp.keccak(sp.pack(sp.record(now=sp.now, s=sp.sender, tid=token_id)))

            self.data.ledger[token_id] = sp.sender
            self.data.hashes[token_id] = token_hash
            self.token_id_set.add(self.data.all_tokens, token_id)

            i.set(i - 1)


class FA2_script(FA2_core):
    @sp.entry_point
    def set_script(self, script):
        sp.verify(~ self.is_locked(), message = self.error_message.locked())
        sp.verify(self.is_administrator(sp.sender), message = self.error_message.not_admin())
        sp.set_type(script, sp.TString)
        self.data.script.set(script)

class FA2_base_uri(FA2_core):
    @sp.entry_point
    def set_base_uri(self, params):
        sp.set_type(params, sp.TBytes)
        sp.verify(~ self.is_locked(), message = self.error_message.locked())
        sp.verify(self.is_administrator(sp.sender), message = self.error_message.not_admin())
        self.data.base_uri = params

class FA2_token_metadata(FA2_core):
    def set_token_metadata_view(self):
        def token_metadata(self, token_id):
            """
            Return the token-metadata URI for the given token.

            For a reference implementation, dynamic-views seem to be the
            most flexible choice.
            """
            sp.set_type(token_id, sp.TNat)

            sp.verify(token_id < self.data.all_tokens, message = self.error_message.token_undefined())
            token_hash = self.data.hashes[token_id]

            metadata = FA2.make_metadata(
                name = "Blocks on Blocks",
                decimals = 0,
                symbol= "BOB",
                token_hash = token_hash,
                uri = self.data.base_uri + bytes_of_nat(token_id)
            )

            sp.result(sp.record(token_id  = token_id, token_info = metadata))

        self.token_metadata = sp.offchain_view(pure = True, doc = "Get Token Metadata")(token_metadata)

    def make_metadata(symbol, name, decimals, token_hash, uri):
        "Helper function to build metadata JSON bytes values."
        return (sp.map(l = {
            # Remember that michelson wants map already in ordered
            "decimals" : sp.utils.bytes_of_string("%d" % decimals),
            "name" : sp.utils.bytes_of_string(name),
            "symbol" : sp.utils.bytes_of_string(symbol),
            "token_hash" : token_hash,
            "" : uri,
        }))


class FA2(FA2_token_metadata, FA2_mint, FA2_administrator, FA2_pause, FA2_lock, FA2_script, FA2_base_uri, FA2_core):

    @sp.offchain_view(pure = True)
    def count_tokens(self):
        """Get how many tokens are in this FA2 contract.
        """
        sp.result(self.token_id_set.cardinal(self.data.all_tokens))

    @sp.offchain_view(pure = True)
    def does_token_exist(self, tok):
        "Ask whether a token ID is exists."
        sp.set_type(tok, sp.TNat)
        sp.result(self.data.hashes.contains(tok))

    @sp.offchain_view(pure = True)
    def all_tokens(self):
        sp.result(sp.range(0, self.data.all_tokens))

    @sp.offchain_view(pure = True)
    def total_supply(self, tok):
        sp.verify(tok < self.data.max_editions, message = self.error_message.token_undefined())
        sp.result(sp.nat(1))

    @sp.offchain_view(pure = True)
    def is_operator(self, query):
        sp.set_type(query,
                    sp.TRecord(token_id = sp.TNat,
                               owner = sp.TAddress,
                               operator = sp.TAddress).layout(
                                   ("owner", ("operator", "token_id"))))
        sp.result(
            self.operator_set.is_member(self.data.operators,
                                        query.owner,
                                        query.operator,
                                        query.token_id)
        )

    def __init__(self, config, metadata, admin):
        # Let's show off some meta-programming:
        self.all_tokens.doc = """
        This view is specified (but optional) in the standard.
        """
        list_of_views = [
            self.get_balance
            , self.does_token_exist
            , self.count_tokens
            , self.all_tokens
            , self.is_operator
            , self.total_supply
        ]

        self.set_token_metadata_view()
        list_of_views = list_of_views + [self.token_metadata]

        metadata_base = {
            "version": config.name # will be changed if using fatoo.
            , "description" : (
                "Blocks on Blocks is an abstract NFT collection based on an open source FA2 implementation for generative art."
            )
            , "interfaces": ["TZIP-012", "TZIP-016", "TZIP-021"]
            , "authors": [
                "Achiru <https://github.com/pop123123123>",
                "AntOnChain <https://github.com/antbrl>",
                "Wakob'Hash <https://github.com/nbusser>",
            ]
            , "homepage": "https://github.com/GenArtLabs"
            , "views": list_of_views
            , "permissions": {
                "operator":
                "owner-or-operator-transfer" if config.support_operator else "owner-transfer"
                , "receiver": "owner-no-hook"
                , "sender": "owner-no-hook"
            }
        }
        self.init_metadata("metadata_base", metadata_base)
        FA2_core.__init__(self, config, metadata, paused = False, locked = False, administrator = admin)

## ## Tests
##
## ### Auxiliary Consumer Contract
##
## This contract is used by the tests to be on the receiver side of
## callback-based entry-points.
## It stores facts about the results in order to use `scenario.verify(...)`
## (cf.
##  [documentation](https://smartpy.io/docs/scenarios/testing)).
class View_consumer(sp.Contract):
    def __init__(self, contract):
        self.contract = contract
        self.init(last_sum = 0,
                  operator_support =  not contract.config.support_operator)

    @sp.entry_point
    def reinit(self):
        self.data.last_sum = 0
        # It's also nice to make this contract have more than one entry point.

    @sp.entry_point
    def receive_balances(self, params):
        sp.set_type(params, Balance_of.response_type())
        self.data.last_sum = 0
        sp.for resp in params:
            self.data.last_sum += resp.balance

##
## ## Global Environment Parameters
##
## The build system communicates with the python script through
## environment variables.
## The function `environment_config` creates an `FA2_config` given the
## presence and values of a few environment variables.
def global_parameter(env_var, default):
    try:
        if os.environ[env_var] == "true" :
            return True
        if os.environ[env_var] == "false" :
            return False
        return default
    except:
        return default

def environment_config():
    return FA2_config(
        debug_mode = global_parameter("debug_mode", False),
        readable = global_parameter("readable", True),
        force_layouts = global_parameter("force_layouts", True),
        support_operator = global_parameter("support_operator", True),
        allow_self_transfer = global_parameter("allow_self_transfer", False),
        max_editions = global_parameter("max_editions", 4096),
        price = global_parameter("price", 1000000),
        base_uri = global_parameter("base_uri", "https://blocks-on-blocks.herokuapp.com/api/"),
    )


@sp.add_test(name = "Basic test", is_default=True)
def basic_test():
    run_basic_test(environment_config())

@sp.add_test(name = "Mint test", is_default=True)
def tests_mint():
    run_mint_test(environment_config())

@sp.add_test(name = "Tests pause", is_default=True)
def tests_pause():
    run_tests_pause(environment_config())

@sp.add_test(name = "Lock test", is_default=True)
def tests_lock():
    run_tests_lock(environment_config())

@sp.add_test(name = "tzip12 tests transfer", is_default=True)
def tests_transfer():
    run_tests_transfer(environment_config())

@sp.add_test(name = "tzip12 tests multi-transfer", is_default=True)
def tests_multi_transfer():
    run_tests_multi_transfer(environment_config())

@sp.add_test(name = "tzip12 tests operator", is_default=True)
def tests_operator():
    run_tests_operator(environment_config())

@sp.add_test(name = "tzip12 tests multi operators", is_default=True)
def tests_multi_operators():
    run_tests_multi_operators(environment_config())

@sp.add_test(name = "tzip12 tests remove operators", is_default=True)
def tests_remove_operator():
    run_tests_remove_operator(environment_config())

@sp.add_test(name = "Tests set admin", is_default=True)
def tests_set_administrator():
    run_tests_set_administrator(environment_config())

@sp.add_test(name = "Tests mutez transfer", is_default=True)
def tests_mutez_transfer():
    run_tests_mutez_transfer(environment_config())

@sp.add_test(name = "Tests get balance", is_default=True)
def tests_get_balance():
    run_tests_get_balance(environment_config())

@sp.add_test(name = "Tests count token", is_default=True)
def tests_count_tokens():
    run_tests_count_tokens(environment_config())

@sp.add_test(name = "Tests does token exist", is_default=True)
def tests_does_token_exist():
    run_tests_does_token_exist(environment_config())

@sp.add_test(name = "Tests all tokens", is_default=True)
def tests_all_tokens():
    run_tests_all_tokens(environment_config())

@sp.add_test(name = "Tests is operator", is_default=True)
def tests_is_operator():
    run_tests_is_operator(environment_config())

@sp.add_test(name = "Tests token metadata", is_default=True)
def tests_token_metadata():
    run_token_metadata(environment_config())

@sp.add_test(name = "Tests set mint parameters", is_default=True)
def tests_set_mint_parameters():
    run_tests_set_mint_parameters(environment_config())



def add_test(config, is_default = True):
    @sp.add_test(name = config.name, is_default = is_default)
    def test():
        scenario = sp.test_scenario()
        scenario.h1("FA2 Contract Name: " + config.name)
        scenario.table_of_contents()
        # sp.test_account generates ED25519 key-pairs deterministically:
        admin = sp.test_account("Administrator")
        alice = sp.test_account("Alice")
        bob   = sp.test_account("Robert")
        scenario.show([admin, alice, bob])
        c1 = FA2(config = config,
                    metadata = sp.utils.metadata_of_url("https://example.com"),
                    admin = admin.address)
        scenario += c1
        scenario.h3("Consumer Contract for Callback Calls.")
        consumer = View_consumer(c1)
        scenario += consumer

        c1.mint(1).run(sender=alice, amount=sp.mutez(4000000))
        c1.mint(1).run(sender=alice, amount=sp.mutez(4000000))
        c1.mint(1).run(sender=alice, amount=sp.mutez(4000000))
        scenario.p("Consumer virtual address: "
                    + consumer.address.export())
        scenario.h2("Balance-of.")
        def arguments_for_balance_of(receiver, reqs):
            return (sp.record(
                callback = sp.contract(
                    Balance_of.response_type(),
                    receiver.address,
                    entry_point = "receive_balances").open_some(),
                requests = reqs))
        c1.balance_of(arguments_for_balance_of(consumer, [
            sp.record(owner = alice.address, token_id = 0),
            sp.record(owner = alice.address, token_id = 1),
            sp.record(owner = alice.address, token_id = 2)
        ]))
        scenario.verify(consumer.data.last_sum == 3)
## ## Standard “main”
##
## This specific main uses the relative new feature of non-default tests
## for the browser version.
if "templates" not in __name__:
    sp.add_compilation_target("FA2_comp", FA2(config = environment_config(),
                              metadata = sp.utils.metadata_of_url("ipfs://QmNe3gg9kUrzDBUQuN2TxUBzokxU9cQKFwgEY9bz8y7tX5"),
                              admin = sp.address("tz1MTMXNd8fxbUuGHsYyBnFAPAFdA6GVyKVT")))
